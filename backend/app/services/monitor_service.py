"""Read-only dashboard service over the ML pipeline's output files (see services/environment.py).

Terminology used in every payload:
  observed   = processed NOAA OISST data (measurement-based analysis)
  forecast   = ConvLSTM model output (latest: issued from the last processed day; hindcast: issued earlier, with truth)
  derived    = computed from observed/forecast fields (anomaly, percentile, risk, heatwave state)
"""
from __future__ import annotations

from datetime import date as date_cls, datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from app.services import risk_service as risk
from app.services import environment as _environment
from app.services.environment import Env, OutputsUnavailable, env as load_env, read_json  # noqa: F401

N_HORIZONS = 7
BLOCK = 8  # hotspot aggregation block, cells (8 x 0.25 deg = 2 deg)

# Dashboard-defined SST-departure categories (|anomaly|, degC). Same words as the project's levels but NOT ecological risk.
SEVERITY = [(3.0, "CRITICAL"), (2.0, "HIGH"), (1.0, "MEDIUM")]

REGIONS = {  # lat_min, lat_max, lon_min, lon_max
    "all": (-90, 90, -180, 180),
    "north": (35, 90, -180, 180),
    "south": (-90, 35, -180, 180),
    "west": (-90, 90, -180, -140),
    "east": (-90, 90, -140, 180),
}

LAYERS = {
    "observed": ("Observed SST (latest day)", "observed"),
    "observed_anomaly": ("Observed SST anomaly vs. 2012-2023 average", "derived"),
    "forecast": ("Forecast SST", "forecast"),
    "forecast_anomaly": ("Forecast SST anomaly vs. 2012-2023 average", "forecast"),
    "heatwave": ("Marine-heatwave anomaly (active areas only)", "derived"),
    "risk": ("Project environmental risk indicator (0-1)", "derived"),
    "hindcast": ("Hindcast SST (forecast issued 7 days before verification)", "forecast"),
    "hindcast_truth": ("Observed SST for the hindcast days", "observed"),
    "hindcast_error": ("Hindcast error (forecast - observed)", "evaluation"),
}
DIVERGING = {"observed_anomaly", "forecast_anomaly", "hindcast_error"}


def severity_for(abs_anomaly: float) -> str | None:
    for threshold, name in SEVERITY:
        if abs_anomaly >= threshold:
            return name
    return None


def _grid(a: np.ndarray) -> list:
    return [[None if np.isnan(v) else round(float(v), 2) for v in row] for row in a]


def _mean(a) -> float | None:
    v = a[~np.isnan(a)]
    return round(float(v.mean()), 3) if v.size else None


def _opt(v) -> float | None:
    return None if v is None or np.isnan(v) else round(float(v), 2)


def metrics() -> dict:
    return read_json(_environment.processed_dir() / "model" / "model_metrics.json")


def performance() -> dict:
    m = metrics()
    b = m["baselines"]
    out = {
        "split": m["split"], "date_range": m["date_range"], "n_windows": m["n_windows"],
        "n_valid_cells": m.get("n_valid_cells"),
        "horizons": m["horizons"], "checkpoint": m.get("checkpoint"),
        "models": {
            name: {k: r[k] for k in ("mae", "rmse", "r2", "mean_mae", "mean_rmse", "mean_r2")}
            for name, r in b.items()
        },
        "mae_skill_vs_persistence": b["convlstm"]["mae_skill_vs_persistence"],
        "rmse_skill_vs_persistence": b["convlstm"]["rmse_skill_vs_persistence"],
    }
    try:
        meta = read_json(_environment.processed_dir() / "meta.json")
        sp = meta.get("splits", {})
        out["methodology"] = {
            "model": "ConvLSTM (2 layers, 32 hidden channels, 3x3 kernels, residual prediction head)",
            "task": f"Forecast daily SST 1-{max(m['horizons'])} days ahead from the previous {meta.get('lookback_days')} days "
                    f"(channels: {', '.join(meta.get('forecast_channels', []))}); grid {len(meta['lat'])}x{len(meta['lon'])} at {meta['resolution']} degrees",
            "splits": {k: {"start": v["start"], "end": v["end"], "days": v["days"], "windows": v["forecast_windows"]} for k, v in sp.items()},
            "baselines": "Persistence (repeat the last observed map) and climatology (2012-2023 daily average)",
            "evaluation": "All three methods are scored on identical ocean cells observed on both the forecast-origin day and the target day; the test split is never used for training or model selection.",
        }
    except OutputsUnavailable:
        out["methodology"] = None
    try:
        h = read_json(_environment.processed_dir() / "model" / "training_history.json")
        out["training"] = {"epochs": h["epoch"], "train_loss": h["train_loss"], "val_loss": h["val_loss"]}
    except OutputsUnavailable:
        out["training"] = None
    return out


# --- date helpers --------------------------------------------------------------------------------------------------
def available_dates(e: Env) -> dict | None:
    if e.hist is None:
        return None
    d = e.hist["dates"]
    return {"start": str(d[0]), "end": str(d[-1]), "n_days": int(len(d))}


def _observed_on(e: Env, day: str | None) -> tuple[np.ndarray, np.ndarray, str]:
    """(SST, climatology, date) for the latest day, or for a day inside the stored 2-year history."""
    latest = e.info["latest"]["observed_date"]
    if day is None or day == latest:
        return e.z["latest_obs"], e.z["latest_obs_climatology"], latest
    if e.hist is None:
        raise OutputsUnavailable("per-date history is not available; re-run the dashboard export")
    dates = [str(d) for d in e.hist["dates"]]
    if day not in dates:
        raise ValueError(f"date outside the available range {dates[0]} to {dates[-1]}")
    k = dates.index(day)
    raw = e.hist["sst_c"][k].astype("float32")
    sst = np.where(raw == -32768, np.nan, raw / 100.0)
    doy = datetime.strptime(day, "%Y-%m-%d").timetuple().tm_yday
    craw = e.hist["clim_c"][doy - 1].astype("float32")
    clim = np.where(craw == -32768, np.nan, craw / 100.0)
    sst = np.where(e.z["ocean"], sst, np.nan)
    return sst, np.where(e.z["ocean"], clim, np.nan), day


# --- overview --------------------------------------------------------------------------------------------------------
def _trend_word(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta > 0.1:
        return "warming"
    if delta < -0.1:
        return "cooling"
    return "stable"


def overview(db: Session | None = None) -> dict:
    e = load_env()
    z, info = e.z, e.info
    latest = info["latest"]
    full = metrics()
    m = full["baselines"]
    anom_now = risk.current_anomaly(e)
    fc_anom = risk.forecast_anomaly(e)
    fc_sst = [_mean(z["latest_forecast"][h]) for h in range(N_HORIZONS)]
    cur = _mean(z["latest_obs"])
    delta = None if cur is None or fc_sst[-1] is None else round(fc_sst[-1] - cur, 2)
    ocean_cells = int((~np.isnan(z["latest_obs"])).sum())
    big = lambda a: int(np.nansum(np.abs(a) >= SEVERITY[-1][0]))  # noqa: E731
    overlap = risk.species_overlap_blocks(db, e) if db is not None else None
    grids = risk.factor_grids(e, overlap)
    lv = risk.score_to_levels(grids["score"])
    risk_counts = {name: int((lv == i).sum()) for i, name in enumerate(["LOW", "MEDIUM", "HIGH", "CRITICAL"])}
    c, p = m["convlstm"], m["persistence"]
    age_days = (datetime.now(timezone.utc).date() - date_cls.fromisoformat(latest["observed_date"])).days
    hw = e.hwinfo
    hw_summary = None
    if hw is not None:
        ev = hw["events"]
        hw_summary = {
            "active_area_km2": hw["active_area_km2"], "active_share": hw["active_share"], "n_events": len(ev),
            "largest": ev[0] if ev else None, "historical_rank_pct": hw["active_area_historical_rank_pct"],
            "method": hw["method"],
        }
    anom_mean = _mean(anom_now)
    fc_mean = _mean(fc_anom[-1])
    interp = []
    if cur is not None and anom_mean is not None:
        word = "above" if anom_mean >= 0 else "below"
        interp.append(
            f"Across the study region, sea surface temperature on {latest['observed_date']} averaged {cur:.1f} degC, "
            f"{abs(anom_mean):.1f} degC {word} the 2012-2023 average for this time of year.")
    if fc_mean is not None and delta is not None:
        interp.append(
            f"The model expects the regional mean to be {fc_sst[-1]:.1f} degC on {latest['target_dates'][-1]} "
            f"({delta:+.1f} degC versus the last observation; trend: {_trend_word(delta)}), with an anomaly of {fc_mean:+.1f} degC.")
    if hw_summary:
        interp.append(
            f"{hw_summary['active_share'] * 100:.1f}% of the ocean area is in a marine-heatwave state by the project's "
            f"simplified definition, in {hw_summary['n_events']} separate areas.")
    interp.append(f"Latest observed data are {age_days} days old; forecasts are issued from that date, not from today.")
    return {
        "snapshot": info,
        "data_status": {"observed_date": latest["observed_date"], "forecast_dates": latest["target_dates"],
                        "data_age_days": age_days, "available_dates": available_dates(e),
                        "n_nrt_input_days": latest.get("n_nrt_input_days"),
                        "export_generated_at": info.get("generated_at"),
                        "note": latest.get("note")},
        "provenance": {
            "observed": f"Processed NOAA OISST v2.1, last day {latest['observed_date']}",
            "forecast": "ConvLSTM (project model) issued from the last processed day",
            "evaluation": f"Held-out test period {full['date_range'][0]} to {full['date_range'][1]}",
            "derived": "Anomalies, percentiles, marine heatwaves and risk are computed from the fields above",
        },
        "current_sst": cur, "current_anomaly": anom_mean,
        "forecast_sst": fc_sst, "forecast_anomaly": [_mean(fc_anom[h]) for h in range(N_HORIZONS)],
        "forecast_change_c": delta, "forecast_trend": _trend_word(delta),
        "hotspot_cells_now": big(anom_now), "hotspot_cells_day7": big(fc_anom[-1]),
        "hotspot_share_now": round(big(anom_now) / ocean_cells, 4) if ocean_cells else 0,
        "hotspot_share_day7": round(big(fc_anom[-1]) / ocean_cells, 4) if ocean_cells else 0,
        "hotspot_threshold": SEVERITY[-1][0],
        "heatwave": hw_summary,
        "risk": {"counts": risk_counts, "share_high_or_critical": round((risk_counts["HIGH"] + risk_counts["CRITICAL"]) / max(ocean_cells, 1), 4),
                 "factors_used": grids["used"], "species_data_loaded": overlap is not None},
        "improvement": {
            "persistence_mae": p["mean_mae"], "convlstm_mae": c["mean_mae"],
            "relative": round(1 - c["mean_mae"] / p["mean_mae"], 4),
            "better_all_horizons": all(a < b for a, b in zip(c["mae"], p["mae"])),
        },
        "interpretation": interp,
    }


# --- map ---------------------------------------------------------------------------------------------------------------
def map_layer(layer: str, horizon: int, db: Session | None = None, day: str | None = None) -> dict:
    e = load_env()
    z, info = e.z, e.info
    h = horizon - 1
    label, kind = LAYERS[layer]
    unit = "degC"
    if layer in ("observed", "observed_anomaly"):
        sst, clim, date = _observed_on(e, day)
        a = sst if layer == "observed" else sst - clim
    elif layer == "forecast":
        a, date = z["latest_forecast"][h], info["latest"]["target_dates"][h]
    elif layer == "forecast_anomaly":
        a, date = z["latest_forecast"][h] - z["latest_climatology"][h], info["latest"]["target_dates"][h]
    elif layer == "heatwave":
        if e.hw is None:
            raise OutputsUnavailable("marine-heatwave state not found; re-run the dashboard export")
        a, date = e.hw["cur_anom"], info["latest"]["observed_date"]
    elif layer == "risk":
        g = risk.factor_grids(e, risk.species_overlap_blocks(db, e) if db is not None else None)
        a, date, unit = g["score"], info["latest"]["observed_date"], "score 0-1"
    elif layer == "hindcast":
        a, date = z["forecast"][h], info["target_dates"][h]
    elif layer == "hindcast_truth":
        a, date = z["truth"][h], info["target_dates"][h]
    else:  # hindcast_error
        a, date = z["forecast"][h] - z["truth"][h], info["target_dates"][h]
    finite = a[~np.isnan(a)]
    return {
        "layer": layer, "label": label, "kind": kind, "unit": unit, "horizon": horizon, "date": date,
        "diverging": layer in DIVERGING, "coverage": e.bounds,
        "lat": np.round(z["lat"], 3).tolist(), "lon": np.round(z["lon"], 3).tolist(),
        "values": _grid(a),
        "min": round(float(finite.min()), 2) if finite.size else None,
        "max": round(float(finite.max()), 2) if finite.size else None,
    }


# --- location inspector ------------------------------------------------------------------------------------------------
def location(db: Session | None, lat: float, lon: float) -> dict:
    e = load_env()
    c = e.cell(lat, lon)
    base = {"query": {"lat": lat, "lon": lon}, "coverage": e.bounds}
    if c is None:
        return {**base, "in_coverage": False, "message": "Outside the study-region grid: no SST, forecast or risk data for this location."}
    i, j = c
    if not e.is_ocean(i, j):
        return {**base, "in_coverage": True, "is_ocean": False, "message": "Land (or no ocean data) at this location."}
    z, info = e.z, e.info
    sst = float(z["latest_obs"][i, j])
    anom = float(sst - z["latest_obs_climatology"][i, j])
    fc = z["latest_forecast"][:, i, j]
    fc_anom = fc - z["latest_climatology"][:, i, j]
    overlap = risk.species_overlap_blocks(db, e) if db is not None else None
    assess = risk.cell_assessment(e, i, j, overlap)
    hw = None
    if e.hw is not None:
        active = bool(e.hw["active"][i, j])
        hw = {"active": active, "run_days": int(e.hw["run_len"][i, j]) if active else 0,
              "category": int(e.hw["category"][i, j]), "peak_anomaly_c": _opt(e.hw["peak_anom"][i, j]),
              "percentile": _opt(e.hw["percentile"][i, j]), "threshold_c": _opt(e.hw["thr_latest"][i, j]),
              "forecast_above_threshold_day7": bool(e.hw["fc_above"][-1][i, j]) if e.hw["fc_above"].shape[0] else None}
    out = {
        **base, "in_coverage": True, "is_ocean": True,
        "cell": {"lat": round(float(e.lat[i]), 3), "lon": round(float(e.lon[j]), 3)},
        "observed": {"date": info["latest"]["observed_date"], "sst_c": round(sst, 2), "anomaly_c": round(anom, 2),
                     "climatology_c": round(float(z["latest_obs_climatology"][i, j]), 2)},
        "forecast": {"dates": info["latest"]["target_dates"], "sst_c": [_opt(v) for v in fc],
                     "anomaly_c": [_opt(v) for v in fc_anom], "day7_change_c": _opt(fc[-1] - sst)},
        "heatwave": hw, "risk": assess,
    }
    # plain-language explanation
    txt = [f"Sea surface temperature here was {sst:.1f} degC on {info['latest']['observed_date']}, {anom:+.1f} degC versus the 2012-2023 average."]
    txt.append(f"The model forecasts {fc[-1]:.1f} degC on {info['latest']['target_dates'][-1]} ({fc[-1] - sst:+.1f} degC from now).")
    if hw and hw["active"]:
        txt.append(f"This location is inside an active marine-heatwave area (day {hw['run_days']} of the event; project definition).")
    out["explanation"] = txt
    return out


# --- history -----------------------------------------------------------------------------------------------------------
def history(lat: float, lon: float, days: int) -> dict | None:
    e = load_env()
    if e.hist is None:
        raise OutputsUnavailable("per-location history not found; re-run the dashboard export")
    c = e.cell(lat, lon)
    if c is None or not e.is_ocean(*c):
        return None
    i, j = c
    dates = [str(d) for d in e.hist["dates"]][-days:]
    n = len(dates)
    raw = e.hist["sst_c"][-n:, i, j].astype("float32")
    sst = np.where(raw == -32768, np.nan, raw / 100.0)
    doy = np.array([datetime.strptime(d, "%Y-%m-%d").timetuple().tm_yday for d in dates])
    clim = e.hist["clim_c"][doy - 1, i, j].astype("float32") / 100.0
    thr = e.hist["thr_c"][doy - 1, i, j].astype("float32") / 100.0
    anom = sst - clim
    roll = np.array([np.nan if k < 6 else np.nanmean(anom[k - 6:k + 1]) for k in range(n)])
    return {
        "cell": {"lat": round(float(e.lat[i]), 3), "lon": round(float(e.lon[j]), 3)},
        "unit": "degC", "source": "NOAA OISST v2.1 (processed), climatology 2012-2023",
        "series": [{"date": d, "sst": _opt(s), "climatology": _opt(cl), "p90_threshold": _opt(t),
                    "anomaly": _opt(a), "anomaly_7d_mean": _opt(r)}
                   for d, s, cl, t, a, r in zip(dates, sst, clim, thr, anom, roll)],
    }


# --- verification (hindcast) at a point / region -----------------------------------------------------------------------
def point(lat: float, lon: float) -> dict | None:
    e = load_env()
    c = e.cell(lat, lon)
    if c is None or not e.is_ocean(*c):
        return None
    i, j = c
    z, info = e.z, e.info
    last = _opt(z["observed_last"][i, j])
    return {
        "lat": round(float(e.lat[i]), 3), "lon": round(float(e.lon[j]), 3),
        "dates": info["target_dates"], "horizons": info["horizons"],
        "forecast": [_opt(v) for v in z["forecast"][:, i, j]],
        "observed": [_opt(v) for v in z["truth"][:, i, j]],
        "climatology": [_opt(v) for v in z["climatology"][:, i, j]],
        "persistence": None if last is None else [last] * N_HORIZONS,
        "last_observed": last, "last_observed_date": info["input_end_date"],
        "latest": {"observed_date": info["latest"]["observed_date"], "dates": info["latest"]["target_dates"],
                   "sst_c": _opt(z["latest_obs"][i, j]),
                   "forecast": [_opt(v) for v in z["latest_forecast"][:, i, j]],
                   "climatology": [_opt(v) for v in z["latest_climatology"][:, i, j]]},
    }


def region(name: str) -> dict:
    e = load_env()
    z, info = e.z, e.info
    la0, la1, lo0, lo1 = REGIONS[name]
    sel = ((z["lat"] >= la0) & (z["lat"] <= la1))[:, None] & ((z["lon"] >= lo0) & (z["lon"] <= lo1))[None, :]
    sel &= z["ocean"]

    def per_h(a):
        return [_mean(np.where(sel, a[h], np.nan)) for h in range(N_HORIZONS)]

    last = _mean(np.where(sel, z["observed_last"], np.nan))
    dm, dc, dd = z["daily_mean"], z["daily_clim"], z["daily_dates"]
    latest_obs = _mean(np.where(sel, z["latest_obs"], np.nan))
    out = {
        "region": name, "n_cells": int(sel.sum()), "dates": info["target_dates"], "horizons": info["horizons"],
        "forecast": per_h(z["forecast"]), "observed": per_h(z["truth"]),
        "climatology": per_h(z["climatology"]),
        "persistence": None if last is None else [last] * N_HORIZONS, "last_observed": last,
        "last_observed_date": info["input_end_date"],
        "latest": {"observed_date": info["latest"]["observed_date"], "dates": info["latest"]["target_dates"],
                   "sst_c": latest_obs, "forecast": per_h(z["latest_forecast"]),
                   "climatology": per_h(z["latest_climatology"])},
        # whole-domain daily means over the last 90 days of the test split (history chart)
        "history": [{"date": str(d), "sst": round(float(a), 3), "climatology": round(float(c), 3)}
                    for d, a, c in zip(dd[-90:], dm[-90:], dc[-90:])],
    }
    return out


# --- anomaly hotspots ----------------------------------------------------------------------------------------------------
def hotspots(horizon: int, min_abs: float, limit: int, day: str | None = None) -> dict:
    """Anomalous 2x2 degree blocks. horizon 0 = observed anomaly on `day` (default latest observed day);
    horizon 1..7 = latest forecast anomaly."""
    e = load_env()
    z, info = e.z, e.info
    if horizon == 0:
        sst, clim, date = _observed_on(e, day)
        anom, field_sst, field_clim, kind = sst - clim, sst, clim, "observed"
    else:
        h = horizon - 1
        anom = z["latest_forecast"][h] - z["latest_climatology"][h]
        field_sst, field_clim, kind = z["latest_forecast"][h], z["latest_climatology"][h], "forecast"
        date = info["latest"]["target_dates"][h]
    H, W = anom.shape
    rows = []
    for i in range(0, H, BLOCK):
        for j in range(0, W, BLOCK):
            blk = anom[i:i + BLOCK, j:j + BLOCK]
            ok = ~np.isnan(blk)
            if ok.sum() < BLOCK * BLOCK * 0.25:
                continue
            mean = float(blk[ok].mean())
            sev = severity_for(abs(mean))
            if abs(mean) < min_abs or sev is None:
                continue
            la, lo = z["lat"][i:i + BLOCK], z["lon"][j:j + BLOCK]
            persist = None
            if e.hw is not None and horizon == 0 and day in (None, info["latest"]["observed_date"]):
                runs = e.hw["run_len"][i:i + BLOCK, j:j + BLOCK][ok]
                persist = int(np.median(runs[runs > 0])) if (runs > 0).any() else 0
            rows.append({
                "lat": round(float((la[0] + la[-1]) / 2), 2), "lon": round(float((lo[0] + lo[-1]) / 2), 2),
                "lat_min": round(float(la[0]) - 0.125, 3), "lat_max": round(float(la[-1]) + 0.125, 3),
                "lon_min": round(float(lo[0]) - 0.125, 3), "lon_max": round(float(lo[-1]) + 0.125, 3),
                "mean_anomaly": round(mean, 2), "max_anomaly": round(float(blk[ok][np.abs(blk[ok]).argmax()]), 2),
                "value_c": round(float(np.nanmean(field_sst[i:i + BLOCK, j:j + BLOCK])), 2),
                "baseline_c": round(float(np.nanmean(field_clim[i:i + BLOCK, j:j + BLOCK])), 2),
                "persistence_days": persist,
                "cells": int(ok.sum()), "severity": sev, "direction": "warm" if mean > 0 else "cold",
                "date": date, "kind": kind,
                "source": "NOAA OISST v2.1 (observed)" if kind == "observed" else "ConvLSTM forecast",
            })
    rows.sort(key=lambda r: -abs(r["mean_anomaly"]))
    return {"horizon": horizon, "date": date, "kind": kind, "total": len(rows), "items": rows[:limit],
            "categories": [{"min_abs": t, "level": n} for t, n in SEVERITY],
            "available_dates": available_dates(e),
            "basis": "SST (or forecast SST) minus the 2012-2023 daily climatology, averaged over 2x2 degree blocks."}
