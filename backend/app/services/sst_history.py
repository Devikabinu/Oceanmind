"""Historical SST of a place or region over the whole processed record: daily series, monthly/annual aggregation, annual means and anomalies, and a trend.

Everything is read from the processed dataset the rest of the application uses (memory-mapped cubes, the same masks, regions and baseline); nothing is stored a second time
except a small cache of daily region means (`region_series.npz` beside the dataset) that is rebuilt whenever the dataset is rebuilt. A day without data is NaN and is left
out of every statistic: it is never replaced by zero. The trend is a linear fit to the annual mean anomalies of COMPLETE years only and is reported as a trend over the
available record, never as an attribution to climate change."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats as sps

from app.services import environment_store as es
from app.services import geo_regions as geo

MIN_TREND_YEARS = 8            # fewer complete years than this: no trend is estimated
MIN_YEAR_COVERAGE = 0.9        # share of a calendar year's days that must have data for the year to count as complete
MIN_REGION_COVERAGE = 0.5      # share of a region's (area-weighted) ocean cells that must have data on a day for the regional mean to exist
MIN_MONTH_DAYS = 10            # days of data a month needs before a monthly mean is reported
CACHE_NAME = "region_series.npz"
AGGREGATIONS = ("daily", "monthly", "annual")


# ------------------------------------------------------------------------------------------------------------------------------------ data access
def _denorm(store: es.EnvironmentalStore, name: str, a: np.ndarray) -> np.ndarray:
    st = store.stats[name]
    return a.astype("float32") * np.float32(st["std"]) + np.float32(st["mean"])


def _day_order(store: es.EnvironmentalStore):
    """(split, row range) blocks in date order together with their dates."""
    out = []
    for sp in es.SPLITS:
        f = store.ref.path / "cubes" / f"{sp}_dates.npy"
        if f.exists():
            out.append((sp, pd.DatetimeIndex(np.load(f)).normalize()))
    return out


def build_region_series(store: es.EnvironmentalStore) -> dict:
    """Daily area-weighted (cos latitude) mean SST and anomaly of every named region, from one pass over the cubes."""
    regions = list(geo.REGIONS.values())
    H, W = len(store.lat), len(store.lon)
    w = np.cos(np.deg2rad(store.lat))[:, None] * np.ones((1, W))
    masks = np.stack([geo.region_mask(r, store.lat, store.lon) & ~store.land for r in regions], axis=-1).reshape(H * W, len(regions)).astype("float32")
    wm = masks * w.reshape(-1, 1).astype("float32")
    total_w = wm.sum(axis=0)
    ch_sst, ch_an, ch_mask = store.channels.index("sst"), store.channels.index("sst_anom"), store.channels.index("mask_sst")
    dates, sst_m, an_m, n_valid = [], [], [], []
    for sp, d in _day_order(store):
        cube = store._cube(sp)
        for a in range(0, len(d), 300):
            b = min(a + 300, len(d))
            ok = (np.asarray(cube[a:b, ch_mask]) > 0.5) & ~store.land[None]
            v = ok.reshape(b - a, -1).astype("float32")
            for name, ch, acc in (("sst", ch_sst, sst_m), ("sst_anom", ch_an, an_m)):
                x = np.where(ok, _denorm(store, name, np.asarray(cube[a:b, ch])), 0.0).reshape(b - a, -1)
                num, den = x @ wm, v @ wm
                with np.errstate(all="ignore"):
                    acc.append(np.where(den >= MIN_REGION_COVERAGE * total_w, num / den, np.nan).astype("float32"))
            n_valid.append((v @ masks).astype("int32"))
        dates.append(d)
    idx = np.concatenate([d.values for d in dates]).astype("datetime64[D]")
    out = {"dates": idx, "sst": np.concatenate(sst_m), "anom": np.concatenate(an_m), "n_valid": np.concatenate(n_valid), "n_cells": masks.sum(axis=0).astype("int32"),
           "regions": np.array([r.id for r in regions])}
    return out


_cache: dict = {}


def region_series(store: es.EnvironmentalStore) -> dict:
    f = store.ref.path / CACHE_NAME
    stamp = (store.ref.path / "meta.json").stat().st_mtime
    key = (str(f), stamp)
    if key in _cache:
        return _cache[key]
    data = None
    if f.exists() and f.stat().st_mtime >= stamp:
        with np.load(f) as z:
            data = {k: z[k] for k in z.files}
    if data is None:
        data = build_region_series(store)
        tmp = f.with_name("region_series.tmp.npz")
        np.savez_compressed(tmp, **data)
        tmp.replace(f)
    _cache.clear()
    _cache[key] = data
    return data


def cell_series(store: es.EnvironmentalStore, i: int, j: int) -> tuple[pd.DatetimeIndex, np.ndarray, np.ndarray]:
    ch_sst, ch_an, ch_mask = store.channels.index("sst"), store.channels.index("sst_anom"), store.channels.index("mask_sst")
    dates, sst, an = [], [], []
    for sp, d in _day_order(store):
        cube = store._cube(sp)
        ok = np.asarray(cube[:, ch_mask, i, j]) > 0.5
        dates.append(d)
        sst.append(np.where(ok, _denorm(store, "sst", np.asarray(cube[:, ch_sst, i, j])), np.nan))
        an.append(np.where(ok, _denorm(store, "sst_anom", np.asarray(cube[:, ch_an, i, j])), np.nan))
    return pd.DatetimeIndex(np.concatenate([d.values for d in dates])), np.concatenate(sst), np.concatenate(an)


# ------------------------------------------------------------------------------------------------------------------------------------ statistics
def _r(x, d=2):
    return None if x is None or not math.isfinite(x) else round(float(x), d)


def annual_summary(df: pd.DataFrame, period_start: pd.Timestamp, period_end: pd.Timestamp) -> list[dict]:
    out = []
    for year, g in df.groupby(df.index.year):
        first, last = max(pd.Timestamp(year=year, month=1, day=1), period_start), min(pd.Timestamp(year=year, month=12, day=31), period_end)
        expected = int((last - first).days) + 1
        s, a = g["sst"].dropna(), g["anom"].dropna()
        full_year = first == pd.Timestamp(year=year, month=1, day=1) and last == pd.Timestamp(year=year, month=12, day=31)
        coverage = len(s) / expected if expected else 0.0
        out.append({"year": int(year), "mean_sst": _r(s.mean()) if len(s) else None, "mean_anomaly": _r(a.mean(), 3) if len(a) else None,
                    "min_sst": _r(s.min()) if len(s) else None, "max_sst": _r(s.max()) if len(s) else None, "observations": int(len(s)), "expected_days": expected,
                    "coverage": round(coverage, 3), "complete": bool(full_year and coverage >= MIN_YEAR_COVERAGE)})
    return out


def trend(annual: list[dict]) -> dict:
    """Linear fit of annual mean anomaly on year, complete years only. `insufficient_data` unless there are at least MIN_TREND_YEARS of them."""
    yrs = [(a["year"], a["mean_anomaly"]) for a in annual if a["complete"] and a["mean_anomaly"] is not None]
    base = {"method": "ordinary least squares on the annual mean SST anomaly of complete years", "years_used": [y for y, _ in yrs], "n_years": len(yrs), "min_years_required": MIN_TREND_YEARS}
    if len(yrs) < MIN_TREND_YEARS:
        return {**base, "slope_per_year": None, "direction": "insufficient_data", "significant": None, "message": "Insufficient historical data for trend estimation: "
                f"{len(yrs)} complete year(s) with data, at least {MIN_TREND_YEARS} are needed."}
    x, y = np.array([a for a, _ in yrs], dtype=float), np.array([b for _, b in yrs], dtype=float)
    r = sps.linregress(x, y)
    tcrit = sps.t.ppf(0.975, len(x) - 2)
    ci = (r.slope - tcrit * r.stderr, r.slope + tcrit * r.stderr)
    significant = bool(r.pvalue < 0.05)
    direction = ("warming" if r.slope > 0 else "cooling") if significant else "stable"
    span = x.max() - x.min()
    return {**base, "slope_per_year": _r(r.slope, 4), "stderr": _r(r.stderr, 4), "ci95": [_r(ci[0], 4), _r(ci[1], 4)], "p_value": _r(r.pvalue, 4), "r_squared": _r(r.rvalue ** 2, 3),
            "reference_year": _r(float(x.mean()), 3), "anomaly_at_reference_year": _r(r.intercept + r.slope * float(x.mean()), 4), "direction": direction, "significant": significant,
            "change_over_span": _r(r.slope * span, 3), "span_years": int(span),
            "message": ("A statistically significant " + direction + " trend" if significant else "No statistically significant trend") + f" over the available record ({int(x.min())}-{int(x.max())}); "
                       "this is not an attribution to climate change."}


def _aggregate(df: pd.DataFrame, how: str) -> list[dict]:
    if how == "daily":
        d = df.dropna(how="all")
        return [{"date": t.strftime("%Y-%m-%d"), "sst": _r(s), "anomaly": _r(a, 3), "observations": 1} for t, s, a in zip(d.index, d["sst"], d["anom"])]
    rule = "MS" if how == "monthly" else "YS"
    g = df.resample(rule)
    cnt = g["sst"].count()
    mean = g[["sst", "anom"]].mean()
    need = MIN_MONTH_DAYS if how == "monthly" else MIN_MONTH_DAYS * 12
    out = []
    for t in mean.index:
        n = int(cnt.loc[t])
        if n < need and not (how == "annual" and n >= 1 and t.year == df.index[-1].year):
            continue
        out.append({"date": t.strftime("%Y-%m-%d"), "sst": _r(mean.loc[t, "sst"]), "anomaly": _r(mean.loc[t, "anom"], 3), "observations": n})
    return out


# ------------------------------------------------------------------------------------------------------------------------------------ entry point
def _forecast(dataset: str, i: int | None, j: int | None, region: str, store: es.EnvironmentalStore):
    try:
        from app.services import forecast_store
        snap, info, metrics, origin = forecast_store.load(dataset)
        if info["latest"]["observed_date"] != str(store.dates[-1].date()):
            return None
        dates = info["latest"]["target_dates"]
        if i is not None:
            f, c = snap["latest_forecast"][:, i, j], snap["latest_climatology"][:, i, j]
            if not np.isfinite(f).all():
                return None
            sst, an = [float(x) for x in f], [float(a - b) for a, b in zip(f, c)]
        else:
            fc = forecast_store.forecast(dataset, region)
            sst, an = fc["forecast_sst"], fc["forecast_anomaly"]
            if any(x is None for x in sst):
                return None
        return {"kind": "forecast", "label": "Forecast (model prediction, not an observation)", "issued_from": info["latest"]["observed_date"], "model": info["model"],
                "beats_persistence": bool(metrics and all(s > 0 for s in metrics["baselines"]["convlstm"]["mae_skill_vs_persistence"])) if metrics else None,
                "series": [{"date": d, "sst": _r(s), "anomaly": _r(a, 3)} for d, s, a in zip(dates, sst, an)]}
    except Exception:  # noqa: BLE001 - no forecast for this dataset: the history is still returned
        return None


def history(dataset: str | None, region: str | None = None, lat: float | None = None, lon: float | None = None, start_date: str | None = None, end_date: str | None = None,
            aggregation: str = "monthly") -> dict:
    if aggregation not in AGGREGATIONS:
        raise ValueError(f"aggregation must be one of {', '.join(AGGREGATIONS)}")
    if (lat is None) != (lon is None):
        raise ValueError("lat and lon must be given together")
    store = es.get_store(dataset)
    region_id = region or "pacific"
    i = j = None
    location = None
    if lat is not None:
        if not (math.isfinite(lat) and -90 <= lat <= 90):
            raise ValueError("lat must be a number between -90 and 90")
        if not (math.isfinite(lon) and -360 <= lon <= 360):
            raise ValueError("lon must be a number between -360 and 360 (either -180..180 or 0..360)")
        ext = store.extent
        axis_lon = es._axis_lon(store, lon)
        if not (ext["lat_min"] <= lat <= ext["lat_max"] and axis_lon <= ext["lon_max"]):
            raise ValueError("This location is outside the dataset: there is no SST history for it.")
        i = min(int(math.floor((lat - ext["lat_min"]) / store.res)), len(store.lat) - 1)
        j = min(int(math.floor((axis_lon - ext["lon_min"]) / store.res)), len(store.lon) - 1)
        if bool(store.land[i, j]):
            raise ValueError("This location is land: there is no SST history for it.")
        dates, sst, an = cell_series(store, i, j)
        location = {"latitude": float(lat), "longitude": float(lon), "cell": {"lat": round(float(store.lat[i]), 4), "lon": round(float(store.lon[j]), 4),
                                                                               "lon_180": round(float(((store.lon[j] + 180) % 360) - 180), 4)}}
        reg = geo.get_region("pacific") if region is None else geo.get_region(region_id)
        scope = {"type": "location", "name": f"{abs(location['cell']['lat']):.2f}°{'N' if location['cell']['lat'] >= 0 else 'S'}, {abs(location['cell']['lon_180']):.2f}°{'W' if location['cell']['lon_180'] < 0 else 'E'}"}
        n_cells = 1
    else:
        reg = geo.get_region(region_id)
        data = region_series(store)
        k = int(np.flatnonzero(data["regions"] == reg.id)[0])
        if data["n_cells"][k] == 0:
            raise ValueError("The region does not overlap this dataset")
        dates, sst, an = pd.DatetimeIndex(data["dates"]), data["sst"][:, k].astype("float64"), data["anom"][:, k].astype("float64")
        scope = {"type": "region", "name": reg.name}
        n_cells = int(data["n_cells"][k])
    df = pd.DataFrame({"sst": sst, "anom": an}, index=pd.DatetimeIndex(dates))
    first_av, last_av = df.index[0], df.index[-1]
    try:
        t0 = pd.Timestamp(start_date).normalize() if start_date else first_av
        t1 = pd.Timestamp(end_date).normalize() if end_date else last_av
    except (ValueError, TypeError):
        raise ValueError("start_date and end_date must be YYYY-MM-DD") from None
    if t0 > t1:
        raise ValueError("start_date must not be after end_date")
    if t1 < first_av or t0 > last_av:
        raise es.NoDataForDate(f"No SST record between {t0.date()} and {t1.date()}: the dataset covers {first_av.date()} to {last_av.date()}.", latest=str(last_av.date()), first=str(first_av.date()))
    t0, t1 = max(t0, first_av), min(t1, last_av)
    df = df.loc[t0:t1]
    valid = df["sst"].dropna()
    annual = annual_summary(df, t0, t1)
    tr = trend(annual)
    complete = [a for a in annual if a["complete"] and a["mean_sst"] is not None]
    change = None
    if len(complete) >= 2:
        change = {"from_year": complete[0]["year"], "to_year": complete[-1]["year"], "mean_sst_change": _r(complete[-1]["mean_sst"] - complete[0]["mean_sst"], 2),
                  "mean_anomaly_change": _r(complete[-1]["mean_anomaly"] - complete[0]["mean_anomaly"], 3) if complete[0]["mean_anomaly"] is not None and complete[-1]["mean_anomaly"] is not None else None,
                  "basis": "difference between the annual mean of the last and the first complete year"}
    n_days = int((t1 - t0).days) + 1
    missing_years = [a["year"] for a in annual if a["observations"] == 0]
    desc = store.describe()
    return {
        "dataset": desc, "scope": scope, "region": {"id": reg.id, "name": reg.name}, "location": location, "aggregation": aggregation,
        "period": {"start": str(t0.date()), "end": str(t1.date()), "available_start": str(first_av.date()), "available_end": str(last_av.date()), "years": round(n_days / 365.25, 2)},
        "baseline": store.train_period,
        "series": _aggregate(df, aggregation),
        "annual_summary": annual,
        "trend": tr,
        "change": change,
        "percent_change": None,
        "percent_change_note": "A percentage change of a Celsius temperature depends on an arbitrary zero and is not scientifically meaningful, so none is given; the change is stated in °C.",
        "statistics": {"mean_sst": _r(valid.mean()) if len(valid) else None, "min_sst": _r(valid.min()) if len(valid) else None, "max_sst": _r(valid.max()) if len(valid) else None,
                       "min_date": str(valid.idxmin().date()) if len(valid) else None, "max_date": str(valid.idxmax().date()) if len(valid) else None,
                       "observations": int(len(valid)), "expected_days": n_days, "missing_days": n_days - int(len(valid)), "cells": n_cells,
                       "complete_years": len(complete), "years_without_data": missing_years},
        "forecast": _forecast(desc["id"], i, j, reg.id, store),
        "selected_date": None,
        "kind": "observed" if store.source.get("is_observational") else "generated",
        "statement": f"SST trend over the available historical record ({t0.year}-{t1.year}); a record of this length describes variability and change over these years and does not by itself establish climate change.",
        "limitations": ["Daily values with no data are left out of every statistic and never treated as zero.",
                        "Years that are partial or have less than 90% of their days are shown but not used for the trend.",
                        "Regional values are area-weighted means over the region's ocean cells and need at least half of them to have data that day."]
        + list(desc.get("limitations") or []),
    }
