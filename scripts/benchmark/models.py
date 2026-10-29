"""The three benchmark models. All take x: (B, T=7, C=6, H, W) normalised channels and return (B, 7, 1, H, W) normalised SST for
horizons 1..7, with the SAME residual form as the project's ConvLSTM (output = learned change + last observed SST map), so the only
difference between the models is how they use space and time:

  CNN-only   spatial convolutions over the 7 frames stacked as channels -> sees space, no recurrent memory
  LSTM-only  each frame flattened to a vector, an LSTM over the 7 vectors -> sees time, no convolutional spatial structure
  Hybrid     the project's own oceanmind_model.OceanConvLSTM, imported unchanged -> sees both
"""
from __future__ import annotations

import sys
from pathlib import Path

import torch
from torch import nn

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oceanmind_model.model import OceanConvLSTM, count_parameters  # noqa: E402  (existing code, not modified)


class CNNOnly(nn.Module):
    def __init__(self, in_ch=6, T=7, width=62, n_h=7, residual=True, sst_channel=0):
        super().__init__()
        self.cfg = dict(in_ch=in_ch, T=T, width=width, n_h=n_h, residual=residual, sst_channel=sst_channel)
        self.in_ch, self.T, self.residual, self.sst_channel = in_ch, T, residual, sst_channel
        self.net = nn.Sequential(
            nn.Conv2d(T * in_ch, width, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(width, width, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(width, width, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(width, width, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(width, n_h, 1))

    def forward(self, x):
        B, T, C, H, W = x.shape
        out = self.net(x.reshape(B, T * C, H, W))
        if self.residual:
            out = out + x[:, -1, self.sst_channel:self.sst_channel + 1]
        return out.unsqueeze(2)


class LSTMOnly(nn.Module):
    def __init__(self, in_ch=6, T=7, H=32, W=40, bottleneck=7, n_h=7, residual=True, sst_channel=0):
        super().__init__()
        self.cfg = dict(in_ch=in_ch, T=T, H=H, W=W, bottleneck=bottleneck, n_h=n_h, residual=residual, sst_channel=sst_channel)
        self.n_h, self.H, self.W, self.residual, self.sst_channel = n_h, H, W, residual, sst_channel
        self.inp = nn.Linear(in_ch * H * W, bottleneck)          # whole frame flattened: no spatial structure is kept
        self.lstm = nn.LSTM(bottleneck, bottleneck, batch_first=True)
        self.out = nn.Linear(bottleneck, n_h * H * W)

    def forward(self, x):
        B, T, C, H, W = x.shape
        seq, _ = self.lstm(self.inp(x.reshape(B, T, C * H * W)))
        out = self.out(seq[:, -1]).reshape(B, self.n_h, H, W)
        if self.residual:
            out = out + x[:, -1, self.sst_channel:self.sst_channel + 1]
        return out.unsqueeze(2)


def n_params(m) -> int:
    return sum(p.numel() for p in m.parameters() if p.requires_grad)


def build_hybrid(in_ch=6, n_h=7, sst_channel=0):
    """The project's existing architecture with the project's config.yaml model settings (hidden 32, k=3, 2 layers, head 32, residual)."""
    return OceanConvLSTM(in_ch, 32, 3, 2, 32, n_h, True, sst_channel)


def build_cnn(budget, H, W, T=7, in_ch=6, n_h=7):
    best = min(range(8, 160), key=lambda w: abs(n_params(CNNOnly(in_ch, T, w, n_h)) - budget))
    return CNNOnly(in_ch, T, best, n_h)


def build_lstm(budget, H, W, T=7, in_ch=6, n_h=7):
    best = min(range(2, 64), key=lambda k: abs(n_params(LSTMOnly(in_ch, T, H, W, k, n_h)) - budget))
    return LSTMOnly(in_ch, T, H, W, best, n_h)


def build_all(budget, H, W, T=7, in_ch=6, n_h=7):
    return {"cnn_only": build_cnn(budget, H, W, T, in_ch, n_h), "lstm_only": build_lstm(budget, H, W, T, in_ch, n_h),
            "hybrid_convlstm": build_hybrid(in_ch, n_h)}


if __name__ == "__main__":
    for name, m in build_all(127239, 32, 40).items():
        print(f"{name:<16} params {n_params(m):>8,}  {getattr(m, 'cfg', '')}")
    x = torch.randn(2, 7, 6, 32, 40)
    print({n: tuple(m(x).shape) for n, m in build_all(127239, 32, 40).items()})
