"""Train-only z-score normalisation on ocean cells. After z-scoring, land and still-missing cells are set to 0
(= the training mean); the mask channels carry the missingness information.
All routines work in time chunks so they also run on memory-mapped cubes."""
from __future__ import annotations

import numpy as np

CHUNK = 256


def continuous_channels(names):
    return [i for i, n in enumerate(names) if not n.startswith(("mask_", "doy_"))]


def _rows(sl, n):
    a = 0 if sl.start is None else sl.start
    b = n if sl.stop is None else sl.stop
    for t in range(a, b, CHUNK):
        yield slice(t, min(t + CHUNK, b))


def _moments(cube, i, sl, ocean):
    """Exact (mean, std, n) over finite ocean values; two passes in float64."""
    n, s = 0, 0.0
    for c in _rows(sl, cube.shape[0]):
        v = cube[c, i][:, ocean]
        v = v[np.isfinite(v)]
        n += v.size
        s += float(v.sum(dtype="float64"))
    if n == 0:
        return 0.0, 0.0, 0
    mean, ss = s / n, 0.0
    for c in _rows(sl, cube.shape[0]):
        v = cube[c, i][:, ocean].astype("float64")
        v = v[np.isfinite(v)]
        ss += float(((v - mean) ** 2).sum())
    return mean, (ss / n) ** 0.5, n


def fit_stats(cube, names, train_sl, ocean, min_std):
    """Per-channel mean/std over finite ocean values of the TRAIN rows only."""
    out = {}
    for i in continuous_channels(names):
        m, sd, n = _moments(cube, i, train_sl, ocean)
        out[names[i]] = {"mean": m, "std": max(sd, min_std), "raw_std": sd, "n": n}
    return out


def zscore(cube, names, stats):
    """In place; NaNs stay NaN."""
    for i in continuous_channels(names):
        s = stats[names[i]]
        for c in _rows(slice(None), cube.shape[0]):
            cube[c, i] = (cube[c, i] - s["mean"]) / s["std"]
    return cube


def moments(cube, names, sl, ocean):
    """(mean, std) of each continuous channel over finite ocean values in rows `sl` (call before finish)."""
    return {names[i]: _moments(cube, i, sl, ocean)[:2] for i in continuous_channels(names)}


def finish(cube, ocean):
    """In place: land -> 0, remaining NaN -> 0."""
    for c in _rows(slice(None), cube.shape[0]):
        blk = cube[c]
        blk[:, :, ~ocean] = 0.0
        np.nan_to_num(blk, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
        cube[c] = blk
    return cube
