"""Hard assertions on the build outputs."""
from __future__ import annotations

import numpy as np

from .splits import check_disjoint


def check_no_nan(name, cube, ocean):
    for t in range(0, cube.shape[0], 256):
        blk = np.asarray(cube[t:t + 256])
        assert np.isfinite(blk).all(), f"{name}: non-finite values in final tensor"
        assert np.isfinite(blk[:, :, ocean]).all(), f"{name}: NaN on ocean cells"


def check_train_norm(moms: dict, stats: dict, tol: float):
    """Normalised train channels must have mean~0 / std~1 (skipping constant channels)."""
    for ch, (m, s) in moms.items():
        if stats[ch]["raw_std"] < 1e-6:
            continue  # degenerate (constant) channel
        assert abs(m) < tol, f"train mean of '{ch}' is {m:.2e}, expected ~0"
        assert abs(s - 1) < tol, f"train std of '{ch}' is {s:.4f}, expected ~1"


def check_splits(splits: dict):
    check_disjoint(splits)


def check_windows(index, split, lookback, horizons, n_days):
    if len(index) == 0:
        return
    assert index.start_idx.min() >= 0
    assert index.start_idx.max() + lookback - 1 + max(horizons) < n_days, f"{split.name}: window leaves the split"
    assert index.start_date.min() >= split.start and index.target_last_date.max() <= split.end, \
        f"{split.name}: window dates outside split range"
