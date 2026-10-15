"""Marine-heatwave indicators from the processed NOAA OISST cubes (simplified Hobday et al. 2016).

Method (per ocean cell, daily SST):
  * threshold  = seasonally varying 90th percentile of SST in an 11-day window around each day-of-year, pooled over the
                 BASELINE years (train split, 2012-2023), then smoothed with a 31-day circular moving average;
  * exceedance = SST > threshold;  gaps of <= 2 days between exceedances are bridged;  runs shorter than 5 days dropped;
  * intensity  = SST - climatology (the project's smoothed train-period daily mean);
  * category   = floor(peak intensity / (threshold - climatology)), I..IV (Hobday's "multiples of the 90th-percentile
                 departure"), capped at IV.
Differences from the published definition: a 12-year (not 30-year) baseline, the project's climatology, and no sea-ice /
land handling beyond the existing mask. It is therefore a *project-level* indicator, not an official classification.

Outputs (processed/<out_subdir>/dashboard/): heatwave_state.npz, heatwave.json, point_history.npz."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import ndimage

BASELINE_END = "2023-12-31"
MIN_EVENT_CELLS = 10          # ignore clusters smaller than this (~7,000 km2) when listing events
HISTORY_DAYS = 730            # per-cell history kept for the backend's point charts
CATEGORY_NAMES = {1: "I (Moderate)", 2: "II (Strong)", 3: "III (Severe)", 4: "IV (Extreme)"}


def _cell_area_km2(lat, res_deg):
    km = 111.32 * res_deg
    return (km * km * np.cos(np.deg2rad(lat))).astype("float64")


def _load_series(root: Path, meta: dict, stats: dict):
    tc = meta["target_channel"]
    names = meta["channels"]
    mu, sd = stats["channels"][tc]["mean"], stats["channels"][tc]["std"]
    ocean = ~np.load(root / "land_mask.npy")
    parts, dates = [], []
    for split in ("train", "val", "test"):
        cube = np.load(root / "cubes" / f"{split}.npy", mmap_mode="r")
        d = pd.DatetimeIndex(np.load(root / "cubes" / f"{split}_dates.npy"))
        sst = np.asarray(cube[:, names.index(tc)], dtype="float32") * np.float32(sd) + np.float32(mu)
        ok = (np.asarray(cube[:, names.index(f"mask_{tc}")]) > 0.5) & ocean
        parts.append(np.where(ok, sst, np.nan).astype("float32"))
        dates.append(d)
    return np.concatenate(parts), dates[0].append(dates[1]).append(dates[2]), ocean


def _baseline_threshold(sst, dates, pct=90.0, half_window=5, smooth=31):
    """(366,H,W) seasonally varying percentile threshold from baseline days only."""
    base = np.asarray(dates <= pd.Timestamp(BASELINE_END))
    doy = dates.dayofyear.to_numpy()
    sb, db = sst[base], doy[base]
    thr = np.full((366,) + sst.shape[1:], np.nan, dtype="float32")
    for d in range(1, 367):
        dist = np.minimum(np.abs(db - d), 366 - np.abs(db - d))
        sel = dist <= half_window
        if sel.any():
            with np.errstate(all="ignore"):
                thr[d - 1] = np.nanpercentile(sb[sel], pct, axis=0)
    # circular moving average over day-of-year
    filled = ndimage.uniform_filter1d(np.nan_to_num(thr, nan=0.0), size=smooth, axis=0, mode="wrap")
    return np.where(np.isnan(thr).all(axis=0)[None], np.nan, filled).astype("float32")


def detect_runs(exceed, min_days=5, max_gap=2):
    """Hobday-style event mask from a (T, ...) boolean exceedance array.

    Gaps of <= `max_gap` days between exceedance days are bridged; a day belongs to an event if the (bridged) run that
    contains it is >= `min_days` long. Runs still in progress on the last day are right-censored: they only count once
    they have already reached `min_days`. Returns (mhw bool array, rl int16 array = consecutive bridged days ending on
    each day)."""
    T = exceed.shape[0]
    # edge-pad both ends so the first/last days are not eroded by the closing (padding repeats the edge day, so it can
    # never bridge a gap that is not already bounded by exceedance on both sides)
    padded = np.concatenate([np.repeat(exceed[:1], max_gap, axis=0), exceed, np.repeat(exceed[-1:], max_gap, axis=0)])
    size = max_gap + 1
    closed = ndimage.binary_closing(padded, structure=np.ones((size,) + (1,) * (exceed.ndim - 1), bool))[max_gap:max_gap + T]
    rl = np.zeros(exceed.shape, dtype="int16")
    rl[0] = closed[0]
    for t in range(1, T):
        rl[t] = np.where(closed[t], rl[t - 1] + 1, 0)
    mhw = np.zeros(exceed.shape, dtype=bool)
    fl = rl[T - 1].copy()                              # final length of the run containing day t
    mhw[T - 1] = closed[T - 1] & (fl >= min_days)
    for t in range(T - 2, -1, -1):
        fl = np.where(closed[t + 1] & closed[t], fl, rl[t])
        mhw[t] = closed[t] & (fl >= min_days)
    return mhw, rl


def _percentile_of_latest(sst, dates, latest_idx):
    """Percentile (0-100) of the latest day's SST among baseline-year SSTs within +-5 days of the same day-of-year."""
    base = np.asarray(dates <= pd.Timestamp(BASELINE_END))
    doy = dates.dayofyear.to_numpy()
    d = int(doy[latest_idx])
    dist = np.minimum(np.abs(doy - d), 366 - np.abs(doy - d))
    sel = base & (dist <= 5)
    samples = sst[sel]
    cur = sst[latest_idx]
    with np.errstate(all="ignore"):
        valid = ~np.isnan(samples)
        below = np.nansum((samples < cur[None]) & valid, axis=0)
        n = valid.sum(axis=0)
        pct = np.where(n > 0, 100.0 * below / np.maximum(n, 1), np.nan)
    return pct.astype("float32")


def compute_heatwaves(root, forecast_latest=None, out_subdir="model"):
    """forecast_latest: optional (7,H,W) degC forecast for the 7 days after the last observed day."""
    root = Path(root)
    meta = json.loads((root / "meta.json").read_text())
    stats = json.loads((root / "stats.json").read_text())
    lat = np.asarray(meta["lat"], dtype="float64")
    lon = np.asarray(meta["lon"], dtype="float64")
    res = float(meta["resolution"])
    sst, dates, ocean = _load_series(root, meta, stats)
    T, H, W = sst.shape

    import warnings, xarray as xr
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clim = np.asarray(xr.open_zarr(root / "climatology.zarr")["sst"].sel(dayofyear=np.arange(1, 367)).values, dtype="float32")
    doy = dates.dayofyear.to_numpy()
    thr = _baseline_threshold(sst, dates)
    anom = sst - clim[doy - 1]
    exceed = sst > thr[doy - 1]
    exceed &= ~np.isnan(sst)

    mhw, rl = detect_runs(exceed)
    del exceed

    area = _cell_area_km2(lat, res)[:, None] * np.ones((1, W))
    area = np.where(ocean, area, 0.0)
    mhw_cells = mhw.sum(axis=(1, 2))
    mhw_area = (mhw * area[None]).sum(axis=(1, 2))
    ocean_area = float(area.sum())
    valid = ~np.isnan(sst)
    cnt = np.maximum(valid.sum(axis=(1, 2)), 1)
    mean_sst = np.where(valid, sst, 0).sum(axis=(1, 2)) / cnt
    mean_anom = np.where(valid, anom, 0).sum(axis=(1, 2)) / cnt

    last = T - 1
    active = mhw[last]
    run_len = np.where(active, rl[last], 0).astype("int32")   # days in the current event (bridged gaps included)
    start_idx = last - run_len + 1
    cur_anom = np.where(active, anom[last], np.nan)
    # peak anomaly within the current run
    peak = np.full((H, W), np.nan, dtype="float32")
    cum = np.zeros((H, W), dtype="float32")           # cumulative intensity of the current event, degC-days
    max_len = int(run_len.max()) if active.any() else 0
    for back in range(max_len):
        inrun = active & (run_len > back)
        peak = np.where(inrun, np.fmax(peak, anom[last - back]), peak)
        cum = np.where(inrun, cum + np.nan_to_num(anom[last - back]), cum)
    delta = np.maximum(thr[doy[last] - 1] - clim[doy[last] - 1], 0.1)
    category = np.where(active, np.clip(np.floor(peak / delta), 1, 4), 0).astype("int8")
    pct = _percentile_of_latest(sst, dates, last)

    fc_above = None
    if forecast_latest is not None:
        fdates = dates[last] + pd.to_timedelta(np.arange(1, forecast_latest.shape[0] + 1), unit="D")
        fthr = thr[fdates.dayofyear.to_numpy() - 1]
        fc_above = (forecast_latest > fthr)

    # connected events at the latest day
    lab, n = ndimage.label(active, structure=np.ones((3, 3)))
    events = []
    for k in range(1, n + 1):
        m = lab == k
        cells = int(m.sum())
        if cells < MIN_EVENT_CELLS:
            continue
        ii, jj = np.where(m)
        start = dates[int(np.median(start_idx[m]))]
        cat_val = int(np.clip(np.round(np.nanmean(peak[m] / delta[m])), 1, 4))
        ev = {
            "id": f"mhw-{dates[last].date()}-{len(events) + 1}",
            "status": "ACTIVE",
            "start_date": str(start.date()),
            "last_observed_date": str(dates[last].date()),
            "duration_days": int(last - int(np.median(start_idx[m])) + 1),
            "cells": cells,
            "area_km2": round(float(area[m].sum()), 0),
            "centroid": {"lat": round(float(lat[ii].mean()), 2), "lon": round(float(lon[jj].mean()), 2)},
            "bbox": {"lat_min": round(float(lat[ii].min()) - res / 2, 3), "lat_max": round(float(lat[ii].max()) + res / 2, 3),
                     "lon_min": round(float(lon[jj].min()) - res / 2, 3), "lon_max": round(float(lon[jj].max()) + res / 2, 3)},
            "current_anomaly_c": round(float(np.nanmean(cur_anom[m])), 2),
            "max_anomaly_c": round(float(np.nanmax(peak[m])), 2),
            "category": cat_val, "category_name": CATEGORY_NAMES[cat_val],
            "cumulative_intensity_c_days": round(float(np.nanmean(cum[m])), 1),
            "max_cumulative_intensity_c_days": round(float(np.nanmax(cum[m])), 1),
            "timeline": [
                {"date": str(dates[t].date()), "area_km2": round(float(area[m & mhw[t]].sum()), 0),
                 "mean_anomaly_c": round(float(np.nanmean(anom[t][m])), 2)}
                for t in range(max(0, last - 59), last + 1)
            ],
            "historical_percentile": round(float(np.nanmean(pct[m])), 1),
            "forecast_still_above_p90_day7": None if fc_above is None else round(float(fc_above[-1][m].mean()), 3),
        }
        events.append(ev)
    events.sort(key=lambda e: -e["area_km2"])
    for i, e in enumerate(events, 1):
        e["id"] = f"mhw-{dates[last].date()}-{i}"

    # historical comparison
    years = {}
    for y in sorted(set(dates.year)):
        sel = np.asarray(dates.year == y)
        years[int(y)] = {
            "days": int(sel.sum()),
            "max_area_km2": round(float(mhw_area[sel].max()), 0),
            "mean_area_km2": round(float(mhw_area[sel].mean()), 0),
            "days_with_heatwave_area_over_5pct": int((mhw_area[sel] > 0.05 * ocean_area).sum()),
        }
    cur_area = float(mhw_area[last])
    rank_pct = round(100.0 * float((mhw_area[:last] < cur_area).mean()), 1)

    out = root / out_subdir / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out / "heatwave_state.npz",
        run_len=run_len.astype("int16"), active=active, cur_anom=cur_anom.astype("float32"),
        peak_anom=peak, category=category, percentile=np.where(ocean, pct, np.nan).astype("float32"),
        thr_latest=thr[doy[last] - 1], clim_latest=clim[doy[last] - 1],
        fc_above=np.zeros((0, H, W), bool) if fc_above is None else fc_above,
    )
    info = {
        "method": "Simplified Hobday et al. (2016): SST above a seasonally varying 90th percentile for >= 5 days "
                  "(gaps <= 2 days bridged). Baseline 2012-2023 (12 years, not the recommended 30). "
                  "Project-level indicator, not an official classification.",
        "baseline": ["2012-01-01", BASELINE_END],
        "data_source": "NOAA OISST v2.1 (processed study-region cubes)",
        "latest_date": str(dates[last].date()),
        "ocean_area_km2": round(ocean_area, 0),
        "active_area_km2": round(cur_area, 0),
        "active_share": round(cur_area / ocean_area, 4),
        "active_area_historical_rank_pct": rank_pct,
        "min_event_cells": MIN_EVENT_CELLS,
        "events": events,
        "yearly": years,
        "daily": {
            "dates": [str(d.date()) for d in dates],
            "mean_sst": np.round(mean_sst, 3).tolist(),
            "mean_anomaly": np.round(mean_anom, 3).tolist(),
            "heatwave_area_km2": np.round(mhw_area, 0).tolist(),
        },
    }
    (out / "heatwave.json").write_text(json.dumps(info))

    # per-cell history for point charts (int16 centi-degrees, -32768 = missing)
    def q(a):
        return np.where(np.isnan(a), -32768, np.round(a * 100)).astype("int16")
    np.savez_compressed(
        out / "point_history.npz",
        dates=np.asarray([str(d.date()) for d in dates[-HISTORY_DAYS:]], dtype="U10"),
        sst_c=q(sst[-HISTORY_DAYS:]), clim_c=q(clim), thr_c=q(thr),
    )
    return info
