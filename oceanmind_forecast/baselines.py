"""Baseline forecasters. All operate in physical units (degC) and return (N, n_horizons, H, W)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def persistence_forecast(x_last, n_horizons) -> np.ndarray:
    """Repeat the latest observed SST map for every horizon.
    x_last: (N, H, W) = last timestep of each input window. Returns (N, n_horizons, H, W)."""
    x_last = np.asarray(x_last)
    if x_last.ndim != 3:
        raise ValueError(f"x_last must be (N,H,W), got {x_last.shape}")
    return np.repeat(x_last[:, None], n_horizons, axis=1)


def climatology_forecast(clim, target_dates) -> np.ndarray:
    """Look up the (TRAIN-only) daily climatology for each target date's day-of-year.
    clim: (366, H, W) indexed by dayofyear-1; target_dates: (N, n_horizons) datetime-like.
    Returns (N, n_horizons, H, W)."""
    clim = np.asarray(clim)
    td = np.asarray(target_dates, dtype="datetime64[ns]")
    doy = pd.DatetimeIndex(td.ravel()).dayofyear.to_numpy().reshape(td.shape)
    if clim.shape[0] < doy.max():
        raise ValueError(f"climatology has {clim.shape[0]} days but target day-of-year reaches {doy.max()}")
    return clim[doy - 1]
