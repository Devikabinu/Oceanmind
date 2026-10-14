"""Clip + gap-fill step shared by the build and inference paths."""
from __future__ import annotations

import numpy as np

from .missing import fill_segments


def _count_nan(a, ocean, in_seg, chunk=256):
    n = 0
    for t in range(0, a.shape[0], chunk):
        m = in_seg[t:t + chunk]
        if m.any():
            n += int(np.isnan(a[t:t + chunk][m][:, ocean]).sum())
    return n


def preclean(cfg, data: dict, ocean: np.ndarray, limits: dict, segments):
    """Land -> NaN, clip to train-derived limits, fill short gaps within each segment.
    Returns (cleaned dict, per-variable fill statistics over ocean cells). Inputs are not modified."""
    out, report = {}, {}
    for v, a in data.items():
        a = a.copy()
        a[:, ~ocean] = np.nan
        lo, hi = limits[v]
        np.clip(a, lo, hi, out=a)
        in_seg = np.zeros(a.shape[0], bool)
        for sl in segments:
            in_seg[sl] = True
        miss_before = _count_nan(a, ocean, in_seg)
        a, fmask = fill_segments(a, segments, cfg.missing.max_gap_days, inplace=True)
        n_filled = int(fmask[:, ocean].sum())
        del fmask
        total = int(in_seg.sum() * ocean.sum())
        miss_after = _count_nan(a, ocean, in_seg)
        report[v] = {
            "ocean_cell_days": total,
            "missing_before": miss_before,
            "filled": n_filled,
            "missing_after": miss_after,
            "pct_missing_before": 100 * miss_before / max(total, 1),
            "pct_of_missing_filled": 100 * n_filled / max(miss_before, 1),
            "pct_missing_after": 100 * miss_after / max(total, 1),
        }
        out[v] = a
    return out, report
