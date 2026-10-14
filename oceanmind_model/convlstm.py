"""ConvLSTM building blocks (Shi et al. 2015). All tensors are (B, T, C, H, W) / (B, C, H, W)."""
from __future__ import annotations

import torch
from torch import nn


class ConvLSTMCell(nn.Module):
    def __init__(self, in_ch, hidden_ch, kernel_size=3):
        super().__init__()
        self.hidden_ch = hidden_ch
        self.gates = nn.Conv2d(in_ch + hidden_ch, 4 * hidden_ch, kernel_size, padding=kernel_size // 2)
        nn.init.zeros_(self.gates.bias)
        with torch.no_grad():
            self.gates.bias[hidden_ch:2 * hidden_ch] = 1.0      # forget-gate bias = 1

    def forward(self, x, state):
        h, c = state
        i, f, o, g = torch.chunk(self.gates(torch.cat([x, h], dim=1)), 4, dim=1)
        c = torch.sigmoid(f) * c + torch.sigmoid(i) * torch.tanh(g)
        h = torch.sigmoid(o) * torch.tanh(c)
        return h, c

    def init_state(self, x):
        z = x.new_zeros(x.shape[0], self.hidden_ch, *x.shape[-2:])
        return z, z.clone()


class ConvLSTM(nn.Module):
    """Stack of ConvLSTM layers. Returns (output sequence of the last layer (B,T,hid,H,W), [(h,c) per layer])."""

    def __init__(self, in_ch, hidden_ch, kernel_size=3, layers=2):
        super().__init__()
        self.cells = nn.ModuleList(ConvLSTMCell(in_ch if i == 0 else hidden_ch, hidden_ch, kernel_size)
                                   for i in range(layers))

    def forward(self, x):
        states = [cell.init_state(x[:, 0]) for cell in self.cells]
        outs = []
        for t in range(x.shape[1]):
            inp = x[:, t]
            for k, cell in enumerate(self.cells):
                states[k] = cell(inp, states[k])
                inp = states[k][0]
            outs.append(inp)
        return torch.stack(outs, dim=1), states
