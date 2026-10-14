"""Masked losses. Only cells with mask > 0 contribute; masked cells are dropped, never filled with zeros."""
from __future__ import annotations

import torch
import torch.nn.functional as F


def masked_loss(pred, target, mask, kind="mse", delta=1.0):
    """Mean of the per-cell loss over valid cells. pred/target/mask broadcast to the same shape
    (mask: 1 = valid ocean cell with an observed target). Returns 0 (with grad) if nothing is valid."""
    pred, target = torch.broadcast_tensors(pred, target)
    valid = torch.broadcast_to(mask > 0, pred.shape)
    # invalid cells are removed by indexing, so NaN/garbage there cannot reach the loss or the gradient
    p, t = pred[valid], target[valid]
    if p.numel() == 0:
        return pred.sum() * 0.0
    if kind == "mse":
        return F.mse_loss(p, t)
    if kind == "huber":
        return F.huber_loss(p, t, delta=delta)
    raise ValueError(f"unknown loss {kind!r}")


def batch_valid_mask(y_mask, ocean):
    """Training/eval mask from a dataset batch: target observed AND ocean. y_mask (B,Hn,H,W), ocean (B,H,W)."""
    return (y_mask > 0.5) & (ocean[:, None] > 0.5)
