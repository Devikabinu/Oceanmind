"""Anomaly analysis for one dataset, date and region: where the strongest warm and cold anomalies are, which have persisted, how the regional anomaly has evolved, and how regions
compare. Everything is derived from the processed SST anomaly cubes (anomaly = SST minus the daily climatology of the baseline period); nothing here is a cause or a forecast."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.services import environment_store as es
from app.services import geo_regions as geo
from app.services.dataset_alerts import region_for

THRESHOLD_C = 1.0            # an "unusual" anomaly for the persistence and share statistics
MIN_SEPARATION_DEG = 6.0     # the strongest-anomaly lists show one cell per area, not a cluster of neighbours
MAX_STREAK_DAYS = 120


def _lon180(x: float) -> float:
    return ((x + 180) % 360) - 180


def _series_block(store: es.EnvironmentalStore, dates: pd.DatetimeIndex) -> np.ndarray:
    """(n_days, H, W) anomaly in degC, NaN where land / no data. Reads the memory-mapped cubes row by row."""
    ch, mk = store.channels.index("sst_anom"), store.channels.index("mask_sst")
    st = store.stats["sst_anom"]
    out = np.full((len(dates), len(store.lat), len(store.lon)), np.nan, dtype="float32")
    for n, t in enumerate(dates):
        split, row = store._index[t]
        cube = store._cube(split)
        a = np.asarray(cube[row, ch], dtype="float32") * np.float32(st["std"]) + np.float32(st["mean"])
        ok = (np.asarray(cube[row, mk]) > 0.5) & ~store.land
        out[n] = np.where(ok, a, np.nan)
    return out


def _thinned(values: np.ndarray, lat: np.ndarray, lon: np.ndarray, count: int, largest: bool) -> list[tuple[int, int, float]]:
    """The `count` most extreme cells, at least MIN_SEPARATION_DEG apart (distance measured on the periodic longitude axis)."""
    v = np.where(np.isfinite(values), values, np.nan)
    flat = np.argsort(np.where(np.isnan(v), -np.inf if largest else np.inf, v), axis=None)
    flat = flat[::-1] if largest else flat
    picked: list[tuple[int, int, float]] = []
    for idx in flat:
        i, j = np.unravel_index(idx, v.shape)
        x = v[i, j]
        if not np.isfinite(x):
            break
        if all(abs(lat[i] - lat[a]) > MIN_SEPARATION_DEG or min(abs(lon[j] - lon[b]) % 360, 360 - abs(lon[j] - lon[b]) % 360) > MIN_SEPARATION_DEG for a, b, _ in picked):
            picked.append((int(i), int(j), float(x)))
            if len(picked) == count:
                break
    return picked


def streak_lengths(block: np.ndarray, threshold: float) -> np.ndarray:
    """(H, W) number of consecutive days, counted back from the last day of `block` (days, H, W), on which each cell stayed at least `threshold` away from normal on the
    same side as on the last day. 0 where the last day is not beyond the threshold or has no data."""
    today = block[-1]
    sign = np.sign(today)
    streak = np.zeros(today.shape, dtype="int16")
    alive = np.isfinite(today) & (np.abs(today) >= threshold)
    for back in range(1, len(block) + 1):
        a = block[-back]
        same = alive & np.isfinite(a) & (np.sign(a) == sign) & (np.abs(a) >= threshold)
        if not same.any():
            break
        streak += same.astype("int16")
        alive = same
    return streak


def analysis(dataset: str | None, date, region: str | None, top: int = 8, timeline_days: int = 365) -> dict:
    store = es.get_store(dataset)
    reg = geo.get_region(region or "pacific")
    t = store.resolve_date(date)
    pos = int(store.dates.get_loc(t))
    mask = es.selection_mask(store, region, None)
    if not mask.any():
        raise ValueError("The region does not overlap this dataset")
    w = np.cos(np.deg2rad(store.lat))[:, None] * np.ones((1, len(store.lon)))

    # one block of recent days: enough for persistence and the timeline
    n_back = min(pos + 1, max(timeline_days, MAX_STREAK_DAYS))
    dates = store.dates[pos - n_back + 1: pos + 1]
    block = _series_block(store, dates)
    today = block[-1]
    ok = mask & np.isfinite(today)

    def wmean(a, m):
        mm = m & np.isfinite(a)
        return float((a[mm] * w[mm]).sum() / w[mm].sum()) if mm.any() else None

    # strongest anomalies
    def cell(i, j, v):
        pct, n = store.historical_anomaly(i, j, t, v)
        la, lo = float(store.lat[i]), float(store.lon[j])
        rid, rname = region_for(la, _lon180(lo))
        return {"lat": la, "lon": lo, "lon_180": _lon180(lo), "anomaly_c": round(v, 2), "region": {"id": rid, "name": rname},
                "historical_percentile": pct, "historical_samples": n}

    masked = np.where(ok, today, np.nan)
    warm = [cell(i, j, v) for i, j, v in _thinned(masked, store.lat, store.lon, top, True) if v > 0]
    cold = [cell(i, j, v) for i, j, v in _thinned(masked, store.lat, store.lon, top, False) if v < 0]

    # persistence: consecutive days ending on `date` with an anomaly beyond the threshold on the same side
    streak = streak_lengths(block, THRESHOLD_C)
    persistent = np.where(ok & (streak >= 7), streak, 0)
    p_cells = [(int(i), int(j), float(persistent[i, j])) for i, j in zip(*np.nonzero(persistent))]
    longest = _thinned(np.where(persistent > 0, persistent.astype("float32"), np.nan), store.lat, store.lon, top, True)
    persistent_list = []
    for i, j, s in longest:
        la, lo = float(store.lat[i]), float(store.lon[j])
        rid, rname = region_for(la, _lon180(lo))
        persistent_list.append({"lat": la, "lon": lo, "lon_180": _lon180(lo), "days": int(s), "anomaly_c": round(float(today[i, j]), 2), "direction": "warm" if today[i, j] > 0 else "cold",
                                "region": {"id": rid, "name": rname}, "capped": bool(s >= len(dates))})
    n_ok = int(ok.sum())

    # rapidly developing: the anomaly is already large and has moved by at least 1.5 degC in the last 7 days
    rapid = []
    if len(dates) > 7:
        change = np.where(ok & np.isfinite(block[-8]), today - block[-8], np.nan)
        for largest, test in ((True, (today >= 1.5) & (change >= 1.5)), (False, (today <= -1.5) & (change <= -1.5))):
            for i, j, v in _thinned(np.where(test, change, np.nan), store.lat, store.lon, top, largest):
                la, lo = float(store.lat[i]), float(store.lon[j])
                rid, rname = region_for(la, _lon180(lo))
                rapid.append({"lat": la, "lon": lo, "lon_180": _lon180(lo), "change_7d_c": round(v, 2), "anomaly_c": round(float(today[i, j]), 2),
                              "direction": "warming" if v > 0 else "cooling", "region": {"id": rid, "name": rname}})

    # timeline of the regional mean anomaly and of the share of cells with an unusual anomaly
    tl_dates, tl_mean, tl_warm, tl_cold = [], [], [], []
    for n, d in enumerate(dates[-timeline_days:]):
        a = block[len(dates) - min(timeline_days, len(dates)) + n]
        m = mask & np.isfinite(a)
        if not m.any():
            continue
        tl_dates.append(str(d.date()))
        tl_mean.append(round(float((a[m] * w[m]).sum() / w[m].sum()), 3))
        tl_warm.append(round(float((a[m] >= THRESHOLD_C).mean()), 4))
        tl_cold.append(round(float((a[m] <= -THRESHOLD_C).mean()), 4))

    # regional comparison on the same date (every named region of the dataset)
    comparison = []
    for r in geo.REGIONS.values():
        rm = geo.region_mask(r, store.lat, store.lon) & np.isfinite(today)
        if not rm.any():
            continue
        comparison.append({"id": r.id, "name": r.name, "mean_anomaly_c": round(wmean(today, rm), 2), "share_warm": round(float((today[rm] >= THRESHOLD_C).mean()), 3),
                           "share_cold": round(float((today[rm] <= -THRESHOLD_C).mean()), 3), "valid_cells": int(rm.sum())})
    comparison.sort(key=lambda r: -r["mean_anomaly_c"])

    mean = wmean(today, ok)
    bl = store.train_period
    return {
        "dataset": store.describe(), "region": {"id": reg.id, "name": reg.name}, "date": str(t.date()), "latest_available_date": str(store.dates[-1].date()),
        "baseline": bl, "threshold_c": THRESHOLD_C,
        "summary": {"mean_anomaly_c": None if mean is None else round(mean, 2), "valid_cells": n_ok, "share_warm": None if not n_ok else round(float((today[ok] >= THRESHOLD_C).mean()), 3),
                    "share_cold": None if not n_ok else round(float((today[ok] <= -THRESHOLD_C).mean()), 3),
                    "persistent_cells": len(p_cells), "persistent_share": None if not n_ok else round(len(p_cells) / n_ok, 4)},
        "strongest_warm": warm, "strongest_cold": cold, "persistent": persistent_list, "rapidly_developing": rapid, "persistence_min_days": 7,
        "timeline": {"dates": tl_dates, "mean_anomaly_c": tl_mean, "share_warm": tl_warm, "share_cold": tl_cold},
        "regions": comparison,
        "method": ("Anomaly = daily SST minus the daily climatology of the baseline period" + (f" ({bl[0][:4]} to {bl[1][:4]})" if bl else "") +
                   f". 'Unusual' means an anomaly of at least {THRESHOLD_C:.0f} degC either way. Persistence counts consecutive days up to the selected date on which a cell stayed on the same side of normal "
                   f"by at least that amount (counted back at most {len(dates)} days). The percentile compares the anomaly with earlier anomalies of the same cell within 15 days of the same time of year."),
        "limits": ["This analysis describes how unusual the temperature is, not why. Causes such as large-scale climate patterns, ocean currents or winds are not part of this dataset, so none is claimed."],
    }
