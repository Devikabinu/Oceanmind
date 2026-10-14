"""Gap filling and robust outlier clipping."""
from __future__ import annotations

import numpy as np


def fill_short_gaps(a: np.ndarray, max_gap: int):
    """Linear time-interpolation of NaN runs of length <= max_gap that are bounded by valid values on
    both sides. Longer runs, and runs touching the series ends, are left NaN. Returns (filled, was_filled)."""
    T = a.shape[0]
    valid = ~np.isnan(a)
    t = np.arange(T, dtype=np.int32)[:, None, None]
    prev = np.maximum.accumulate(np.where(valid, t, np.int32(-1)), axis=0)
    nxt = np.minimum.accumulate(np.where(valid, t, np.int32(T))[::-1], axis=0)[::-1]
    fill = ~valid & (prev >= 0) & (nxt < T) & ((nxt - prev - 1) <= max_gap)
    if not fill.any():
        return a, fill
    pi = np.where(fill, prev, 0)
    ni = np.where(fill, nxt, 0)
    v0 = np.take_along_axis(a, pi, 0)
    v1 = np.take_along_axis(a, ni, 0)
    w = (t - pi) / np.maximum(ni - pi, 1)
    out = a.copy()
    out[fill] = (v0 + w * (v1 - v0))[fill]
    return out, fill


def fill_segments(a: np.ndarray, segments, max_gap: int, inplace: bool = False, band: int = 16):
    """Fill each (start, stop) slice independently so no split borrows values across a boundary.
    Works in latitude bands to bound temporary memory. Returns (array, boolean mask of filled cells)."""
    out = a if inplace else a.copy()
    filled = np.zeros(a.shape, bool)
    for sl in segments:
        for r in range(0, a.shape[1], band):
            blk = out[sl, r:r + band]
            out[sl, r:r + band], filled[sl, r:r + band] = fill_short_gaps(blk, max_gap)
    return out, filled


def compute_limits(a: np.ndarray, ocean: np.ndarray, pct, max_samples=5_000_000, seed=0, chunk=256):
    """Percentile clip limits from ocean cells of `a` (pass TRAIN-period data only). Chunked over time,
    with uniform subsampling when there are more than max_samples values."""
    rng = np.random.default_rng(seed)
    keep = min(1.0, max_samples / max(a.shape[0] * int(ocean.sum()), 1))
    parts = []
    for t in range(0, a.shape[0], chunk):
        v = a[t:t + chunk][:, ocean].ravel()
        v = v[np.isfinite(v)]
        if keep < 1.0:
            v = v[rng.random(v.size) < keep]
        parts.append(v)
    vals = np.concatenate(parts)
    if vals.size == 0:
        return float("-inf"), float("inf")
    lo, hi = np.percentile(vals, pct)
    return float(lo), float(hi)
