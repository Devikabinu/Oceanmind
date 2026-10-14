"""ConvLSTM model, masked loss and training step on tiny synthetic tensors (CPU)."""
import numpy as np
import pytest
import torch

from oceanmind_model import OceanConvLSTM, masked_loss
from oceanmind_model.losses import batch_valid_mask
from oceanmind_model.train import load_checkpoint, save_checkpoint, train_step
from oceanmind_preprocess.config import Cfg

B, T, C, H, W, HZ = 2, 3, 6, 8, 10, 4


def tiny():
    torch.manual_seed(0)
    return OceanConvLSTM(in_channels=C, hidden_channels=4, layers=2, head_channels=4, n_horizons=HZ)


def batch(seed=0):
    g = torch.Generator().manual_seed(seed)
    x = torch.randn(B, T, C, H, W, generator=g)
    ocean = torch.ones(B, H, W)
    ocean[:, :, :2] = 0
    y = x[:, -1:, 0].repeat(1, HZ, 1, 1) + 0.5 * torch.randn(B, HZ, H, W, generator=g)
    return {"x": x, "y": y, "y_mask": torch.ones(B, HZ, H, W), "ocean": ocean}


def cfg():
    return Cfg({"training": {"loss": "mse", "huber_delta": 1.0, "grad_clip": 1.0}})


def test_forward_shapes():
    out = tiny()(batch()["x"])
    assert out.shape == (B, HZ, 1, H, W) and torch.isfinite(out).all()
    with pytest.raises(ValueError):
        tiny()(torch.zeros(B, T, C + 1, H, W))


def test_residual_starts_near_persistence():
    m = tiny()
    with torch.no_grad():
        m.head[-1].weight.zero_(); m.head[-1].bias.zero_()
    x = batch()["x"]
    out = m(x)
    for h in range(HZ):
        torch.testing.assert_close(out[:, h, 0], x[:, -1, 0])


def test_masked_loss_ignores_invalid_cells():
    p, t = torch.zeros(1, 1, 2, 2), torch.zeros(1, 1, 2, 2)
    p[0, 0, 0, 0] = 1.0
    t[0, 0, 1, 1] = float("nan")                                      # invalid cell may even be NaN
    mask = torch.tensor([[[[1, 1], [1, 0]]]])
    assert masked_loss(p, t, mask).item() == pytest.approx(1 / 3)
    assert masked_loss(p, torch.zeros_like(p), torch.zeros_like(mask)).item() == 0.0
    big = torch.zeros(1, 1, 2, 2); big[0, 0, 1, 1] = 1e6
    assert masked_loss(big, torch.zeros_like(big), mask).item() == 0.0   # masked-out error has no effect
    assert masked_loss(p, torch.zeros_like(p), mask, "huber", 0.5).item() == pytest.approx(0.375 / 3)


def test_land_gets_no_gradient():
    m = tiny()
    b = batch()
    x = b["x"].clone().requires_grad_(True)
    mask = batch_valid_mask(b["y_mask"], b["ocean"])
    masked_loss(m(x)[:, :, 0], b["y"], mask).backward()
    assert all(p.grad is not None and torch.isfinite(p.grad).all() and p.grad.abs().sum() > 0
               for p in m.parameters())
    assert not mask[:, :, :, :2].any()                                # land columns are excluded from the loss


def test_train_step_loss_decreases():
    m, b = tiny(), batch()
    opt = torch.optim.AdamW(m.parameters(), lr=1e-2)
    losses = [train_step(m, b, opt, cfg(), torch.device("cpu")) for _ in range(10)]
    assert losses[1] < losses[0] and losses[-1] < losses[0]


def test_checkpoint_roundtrip(tmp_path):
    m, b = tiny(), batch()
    save_checkpoint(tmp_path / "c.pt", m, epoch=3, val_loss=0.5)
    m2, ck = load_checkpoint(tmp_path / "c.pt")
    assert ck["epoch"] == 3
    with torch.no_grad():
        torch.testing.assert_close(m.eval()(b["x"]), m2(b["x"]))
