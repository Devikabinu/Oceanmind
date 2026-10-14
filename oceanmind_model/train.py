"""Training loop. Trains on TRAIN windows, early-stops / selects the best checkpoint on VALIDATION loss.
The test split is never touched here."""
from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Subset

from oceanmind_preprocess.datasets import ForecastDataset

from .losses import batch_valid_mask, masked_loss
from .model import build_model, count_parameters

log = logging.getLogger("oceanmind_model")


def resolve_device(name="auto") -> torch.device:
    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"
    if name == "cuda" and not torch.cuda.is_available():
        log.warning("CUDA requested but unavailable; using CPU")
        name = "cpu"
    return torch.device(name)


def seed_everything(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def make_loader(ds, batch_size, shuffle, num_workers, limit=None, seed=0):
    if limit:
        ds = Subset(ds, np.linspace(0, len(ds) - 1, min(limit, len(ds))).astype(int).tolist())   # evenly spread
    g = torch.Generator().manual_seed(seed)
    return DataLoader(ds, batch_size=batch_size, shuffle=shuffle, num_workers=num_workers, generator=g,
                      persistent_workers=num_workers > 0)


def compute_loss(model, batch, cfg, device):
    x = batch["x"].to(device)
    y = batch["y"].to(device)
    mask = batch_valid_mask(batch["y_mask"].to(device), batch["ocean"].to(device))
    pred = model(x)[:, :, 0]
    return masked_loss(pred, y, mask, cfg.training.loss, cfg.training.huber_delta)


def train_step(model, batch, optimizer, cfg, device):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    loss = compute_loss(model, batch, cfg, device)
    loss.backward()
    if cfg.training.grad_clip:
        torch.nn.utils.clip_grad_norm_(model.parameters(), cfg.training.grad_clip)
    optimizer.step()
    return float(loss.detach())


@torch.no_grad()
def eval_loss(model, loader, cfg, device):
    model.eval()
    tot = n = 0
    for b in loader:
        k = int(b["x"].shape[0])
        tot += float(compute_loss(model, b, cfg, device)) * k
        n += k
    return tot / max(n, 1)


def save_checkpoint(path, model, optimizer=None, **extra):
    torch.save({"model": model.state_dict(), "model_cfg": model.cfg,
                "optimizer": optimizer.state_dict() if optimizer else None, **extra}, path)


def load_checkpoint(path, device="cpu"):
    """Returns (model in eval mode, checkpoint dict)."""
    from .model import OceanConvLSTM
    ck = torch.load(path, map_location=device, weights_only=False)
    model = OceanConvLSTM(**ck["model_cfg"]).to(device)
    model.load_state_dict(ck["model"])
    return model.eval(), ck


def train(cfg, out_subdir="model", epochs=None, batch_size=None, device=None, limit_train=None, limit_val=None):
    t, root = cfg.training, Path(cfg.paths.out_dir)
    epochs = epochs or t.epochs
    bs = batch_size or t.batch_size
    dev = resolve_device(device or t.device)
    seed_everything(t.seed)
    mdir, fdir = root / out_subdir, root / "figures" / out_subdir
    mdir.mkdir(parents=True, exist_ok=True)
    fdir.mkdir(parents=True, exist_ok=True)

    tr, va = ForecastDataset(root, "train"), ForecastDataset(root, "val")      # test split is not loaded
    sst_ch = tr.channels.index(tr.meta["target_channel"])
    model = build_model(cfg, len(tr.channels), len(tr.horizons), sst_ch).to(dev)
    opt = torch.optim.AdamW(model.parameters(), lr=t.learning_rate, weight_decay=t.weight_decay)
    tl = make_loader(tr, bs, True, t.num_workers, limit_train, t.seed)
    vl = make_loader(va, bs, False, t.num_workers, limit_val, t.seed)
    log.info("device=%s params=%d train_windows=%d val_windows=%d batch=%d", dev, count_parameters(model),
             len(tl.dataset), len(vl.dataset), bs)

    hist = {"epoch": [], "train_loss": [], "val_loss": [], "seconds": []}
    best, bad = float("inf"), 0
    info = {"channels": tr.channels, "target_channel": tr.meta["target_channel"], "train_period": "train split only"}
    for ep in range(1, epochs + 1):
        t0, run, n = time.time(), 0.0, 0
        for b in tl:
            k = int(b["x"].shape[0])
            run += train_step(model, b, opt, cfg, dev) * k
            n += k
        v = eval_loss(model, vl, cfg, dev)
        hist["epoch"].append(ep); hist["train_loss"].append(run / max(n, 1)); hist["val_loss"].append(v)
        hist["seconds"].append(time.time() - t0)
        log.info("epoch %d/%d train %.5f val %.5f (%.0fs)", ep, epochs, hist["train_loss"][-1], v, hist["seconds"][-1])
        save_checkpoint(mdir / "last_model.pt", model, opt, epoch=ep, val_loss=v, **info)
        if v < best:
            best, bad = v, 0
            save_checkpoint(mdir / "best_model.pt", model, opt, epoch=ep, val_loss=v, **info)
        else:
            bad += 1
        (mdir / "training_history.json").write_text(json.dumps(
            {**hist, "best_val_loss": best, "best_epoch": hist["val_loss"].index(best) + 1,
             "params": count_parameters(model), "device": str(dev), "batch_size": bs,
             "train_windows": len(tl.dataset), "val_windows": len(vl.dataset),
             "config": {"model": dict(cfg.model), "training": dict(cfg.training)}}, indent=2))
        if bad >= t.patience:
            log.info("early stopping: no val improvement for %d epochs", t.patience)
            break
    _plots(hist, fdir)
    _report(hist, best, count_parameters(model), dev, bs, tl, vl, cfg, mdir / "training_report.md")
    return hist


def _plots(h, fdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for key, name in (("train_loss", "training_loss"), ("val_loss", "validation_loss")):
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(h["epoch"], h[key], "o-")
        ax.set(xlabel="Epoch", ylabel="masked loss (normalised SST)", title=name.replace("_", " "))
        ax.grid(alpha=.3)
        fig.tight_layout(); fig.savefig(fdir / f"{name}.png", dpi=150); plt.close(fig)


def _report(h, best, params, dev, bs, tl, vl, cfg, path):
    L = ["# ConvLSTM training report", "",
         f"- Train windows: {len(tl.dataset)} (2012-01-01..2023-12-31); validation windows: {len(vl.dataset)} (2024). Test split not used.",
         f"- Device: {dev}; batch size {bs}; parameters {params:,}; loss {cfg.training.loss}; lr {cfg.training.learning_rate}.",
         f"- Epochs run: {len(h['epoch'])}; best validation loss {best:.6f} at epoch {h['val_loss'].index(best) + 1}.",
         "- Losses are on normalised SST (train std 5.28 degC), masked to valid ocean cells.", "",
         "| Epoch | Train loss | Val loss | Seconds |", "|---|---|---|---|"]
    L += [f"| {e} | {a:.6f} | {b:.6f} | {s:.0f} |" for e, a, b, s in zip(h["epoch"], h["train_loss"], h["val_loss"], h["seconds"])]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")
