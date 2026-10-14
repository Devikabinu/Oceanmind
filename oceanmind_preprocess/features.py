"""Climatology, anomalies and derived feature channels. Pure numpy; shared by build and inference."""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.ndimage import gaussian_filter1d

KM_PER_DEG = 111.195


def smooth_circular(clim: np.ndarray, sigma: float) -> np.ndarray:
    """NaN-aware circular Gaussian smoothing along axis 0 (day-of-year)."""
    valid = ~np.isnan(clim)
    num = gaussian_filter1d(np.where(valid, clim, 0.0).astype("float64"), sigma, axis=0, mode="wrap")
    den = gaussian_filter1d(valid.astype("float64"), sigma, axis=0, mode="wrap")
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(den > 1e-3, num / den, np.nan)
    return out.astype("float32")


def daily_climatology(a: np.ndarray, times: pd.DatetimeIndex, sigma: float):
    """Per-cell mean by day-of-year (1..366) then smoothed. Pass TRAIN-period data only.
    Returns (raw, smoothed), each (366, H, W)."""
    doy = times.dayofyear.values
    raw = np.full((366,) + a.shape[1:], np.nan, "float32")
    for d in np.unique(doy):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            raw[d - 1] = np.nanmean(a[doy == d], axis=0)
    return raw, smooth_circular(raw, sigma)


def anomaly(a, clim, times):
    return a - clim[times.dayofyear.values - 1]


def doy_channels(times, shape_hw):
    ang = 2 * np.pi * (times.dayofyear.values - 1) / 365.25
    ones = np.ones(shape_hw, "float32")
    return (np.sin(ang)[:, None, None] * ones).astype("float32"), (np.cos(ang)[:, None, None] * ones).astype("float32")


def gradient_magnitude(a: np.ndarray, lat: np.ndarray, res: float) -> np.ndarray:
    """|grad| in value-units per 100 km, spherical metric. Central difference where both neighbours exist,
    one-sided at coasts/gaps, NaN only where the cell itself is NaN."""
    pad = np.pad(a, ((0, 0), (1, 1), (1, 1)), constant_values=np.nan)
    c = pad[:, 1:-1, 1:-1]

    def d(plus, minus, h):
        both = (plus - minus) / (2 * h)
        one_p, one_m = (plus - c) / h, (c - minus) / h
        return np.where(~np.isnan(both), both, np.where(~np.isnan(one_p), one_p, one_m))

    dy = KM_PER_DEG * res
    dx = dy * np.cos(np.deg2rad(lat))[None, :, None]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        gy = d(pad[:, 2:, 1:-1], pad[:, :-2, 1:-1], dy)
        gx = d(pad[:, 1:-1, 2:], pad[:, 1:-1, :-2], dx)
    ok = ~np.isnan(c)
    gx, gy = np.where(ok & np.isnan(gx), 0, gx), np.where(ok & np.isnan(gy), 0, gy)
    return (np.sqrt(gx ** 2 + gy ** 2) * 100).astype("float32")


def rolling_stats(a: np.ndarray, window: int, min_periods: int):
    """Trailing (causal) rolling mean/std over `window` days incl. the current day."""
    s = np.zeros(a.shape, "float64")
    ss = np.zeros(a.shape, "float64")
    n = np.zeros(a.shape, "int16")
    for k in range(window):
        x = a[: a.shape[0] - k]
        v = ~np.isnan(x)
        xz = np.where(v, x, 0.0)
        s[k:] += xz
        ss[k:] += xz ** 2
        n[k:] += v
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = s / n
        std = np.sqrt(np.maximum(ss / n - mean ** 2, 0))
    bad = n < min_periods
    return np.where(bad, np.nan, mean).astype("float32"), np.where(bad, np.nan, std).astype("float32")


def lag(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    out[k:] = a[:-k]
    return out


def _gradient_chunked(a, lat, res, chunk=256):
    out = np.empty(a.shape, "float32")
    for t in range(0, a.shape[0], chunk):
        out[t:t + chunk] = gradient_magnitude(a[t:t + chunk], lat, res)
    return out


def feature_names(cfg, data_keys) -> list:
    """Channel order of the feature cube (must match iter_features)."""
    f = cfg.features
    names = list(data_keys)
    names += [f"{v}_anom" for v in f.anomaly_vars]
    if f.gradient.enabled:
        names.append(f"{f.gradient.var}_grad")
    if f.rolling.enabled:
        for v in f.rolling.vars:
            names += [f"{v}_rmean{f.rolling.window}", f"{v}_rstd{f.rolling.window}"]
    if f.lags.enabled:
        names += [f"{v}_lag{k}" for v in f.lags.vars for k in f.lags.days]
    if f.doy:
        names += ["doy_sin", "doy_cos"]
    names += [f"mask_{v}" for v in data_keys]
    return names


def iter_features(cfg, data: dict, times, lat, clim: dict):
    """Yield (name, (T,H,W) float32 array) one channel at a time, so callers can stream to disk.
    `data` holds gap-filled, clipped arrays with NaN on land/long gaps."""
    f = cfg.features
    for v in data:
        yield v, data[v]
    for v in f.anomaly_vars:
        yield f"{v}_anom", anomaly(data[v], clim[v], times).astype("float32")
    if f.gradient.enabled:
        yield f"{f.gradient.var}_grad", _gradient_chunked(data[f.gradient.var], lat, cfg.grid.resolution)
    if f.rolling.enabled:
        w = f.rolling.window
        for v in f.rolling.vars:
            m, s = rolling_stats(data[v], w, f.rolling.min_periods)
            yield f"{v}_rmean{w}", m
            yield f"{v}_rstd{w}", s
    if f.lags.enabled:
        for v in f.lags.vars:
            for k in f.lags.days:
                yield f"{v}_lag{k}", lag(data[v], k)
    if f.doy:
        s, c = doy_channels(times, next(iter(data.values())).shape[1:])
        yield "doy_sin", s
        yield "doy_cos", c
    for v in data:
        yield f"mask_{v}", (~np.isnan(data[v])).astype("float32")


def assemble_features(cfg, data: dict, times, lat, clim: dict):
    """Build the whole un-normalised (T, C, H, W) cube in memory (used by the short inference window)."""
    names = feature_names(cfg, data.keys())
    T, H, W = next(iter(data.values())).shape
    cube = np.empty((T, len(names), H, W), "float32")
    for i, (n, a) in enumerate(iter_features(cfg, data, times, lat, clim)):
        assert n == names[i], (n, names[i])
        cube[:, i] = a
    return cube, names


def lookback_margin(cfg) -> int:
    """Extra history days inference needs so rolling/lag features and gap filling match training."""
    f = cfg.features
    m = 2 * cfg.missing.max_gap_days + 1
    if f.rolling.enabled:
        m += f.rolling.window
    if f.lags.enabled:
        m += max(f.lags.days)
    return m
