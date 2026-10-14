"""Full forecaster: ConvLSTM encoder over the 7-day window -> small conv head -> 7 future SST frames."""
from __future__ import annotations

import torch
from torch import nn

from .convlstm import ConvLSTM


class OceanConvLSTM(nn.Module):
    """Input  x: (B, T, C, H, W) normalised channels (see meta.json forecast_channels; SST at `sst_channel`).
    Output:      (B, n_horizons, 1, H, W) normalised SST for horizons 1..n_horizons.

    With residual=True the head predicts the change from the last observed SST map, so the model starts at
    persistence and has to learn a correction. The spatial grid is never flattened."""

    def __init__(self, in_channels=6, hidden_channels=32, kernel_size=3, layers=2, head_channels=32,
                 n_horizons=7, residual=True, sst_channel=0):
        super().__init__()
        self.cfg = dict(in_channels=in_channels, hidden_channels=hidden_channels, kernel_size=kernel_size,
                        layers=layers, head_channels=head_channels, n_horizons=n_horizons, residual=residual,
                        sst_channel=sst_channel)
        self.in_channels, self.n_horizons, self.residual, self.sst_channel = in_channels, n_horizons, residual, sst_channel
        self.encoder = ConvLSTM(in_channels, hidden_channels, kernel_size, layers)
        self.head = nn.Sequential(
            nn.Conv2d(hidden_channels, head_channels, 3, padding=1), nn.ReLU(inplace=True),
            nn.Conv2d(head_channels, n_horizons, 1))

    def forward(self, x):
        if x.ndim != 5 or x.shape[2] != self.in_channels:
            raise ValueError(f"expected (B,T,{self.in_channels},H,W), got {tuple(x.shape)}")
        seq, _ = self.encoder(x)
        out = self.head(seq[:, -1])                                  # (B, n_horizons, H, W)
        if self.residual:
            out = out + x[:, -1, self.sst_channel:self.sst_channel + 1]
        return out.unsqueeze(2)


def build_model(cfg, in_channels, n_horizons, sst_channel=0) -> OceanConvLSTM:
    m = cfg.model
    return OceanConvLSTM(in_channels, m.hidden_channels, m.kernel_size, m.layers, m.head_channels, n_horizons,
                         m.residual, sst_channel)


def count_parameters(model) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
