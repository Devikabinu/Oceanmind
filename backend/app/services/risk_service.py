"""Project environmental / ecological risk indicator (explainable, rule-based).

NOT an established published index. It is a transparent weighted combination of four 0-1 factors, each defined below,
intended to rank *monitoring priority* / *potential exposure*. It does not prove biological harm.
"""
from __future__ import annotations

import time
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.biodiversity_observation import BiodiversityObservation
from app.services.environment import Env

BLOCK = 8  # species-overlap aggregation block: 8 cells = 2 degrees
OVERLAP_WINDOW_DAYS = 730
OVERLAP_SATURATION = 3  # >= 3 distinct species recorded in the block -> overlap factor 1.0

WEIGHTS = {"anomaly": 0.35, "persistence": 0.25, "forecast": 0.20, "overlap": 0.20}
LEVELS = [(0.75, "CRITICAL"), (0.5, "HIGH"), (0.25, "MEDIUM"), (0.0, "LOW")]
FACTOR_LEVELS = [(0.66, "HIGH"), (0.33, "MEDIUM"), (0.0, "LOW")]

METHODOLOGY = {
    "name": "Project environmental risk indicator",
    "status": "Project-level, rule-based indicator. Not an established published index and not a prediction of harm.",
    "weights": WEIGHTS,
    "factors": {
        "anomaly": "Size of today's SST anomaly (observed SST minus the 2012-2023 daily average): |anomaly| / 3 degC, capped at 1.",
        "persistence": "Length of the current marine-heatwave run (days above the seasonal 90th percentile, min 5 days): days / 14, capped at 1.",
        "forecast": "Mean absolute forecast anomaly over the next 7 days (ConvLSTM forecast minus climatology): |anomaly| / 3 degC, capped at 1.",
        "overlap": f"Distinct species with OBIS records in the surrounding 2x2 degree block within the last {OVERLAP_WINDOW_DAYS} days: n / {OVERLAP_SATURATION}, capped at 1. Absent records mean 'no available records', not 'no animals'.",
    },
    "levels": "score < 0.25 LOW, < 0.5 MEDIUM, < 0.75 HIGH, otherwise CRITICAL (same bands as the project's risk contract).",
    "weights_note": "Weights are a project choice (stress magnitude and persistence weighted highest); they are not fitted to ecological outcomes.",
    "confidence": "No defensible confidence measure exists for this indicator, so none is shown. Forecast error is reported separately on the Model Performance page.",
    "limitations": [
        "Covers the study region only (20-50N, 160-120W); outside it no data is available.",
        "Species records are a sample from OBIS (uneven effort, up to a few hundred per species); absence of records is not absence of animals.",
        "Observed data end at the date shown; the forecast is model output with typical errors of a few tenths of a degree.",
        "SST is only one stressor; the indicator does not include prey, oxygen, fishing pressure or habitat quality.",
    ],
}


def level_for(score: float) -> str:
    for threshold, name in LEVELS:
        if score >= threshold:
            return name
    return "LOW"


def factor_level(v: float) -> str:
    for threshold, name in FACTOR_LEVELS:
        if v >= threshold:
            return name
    return "LOW"


def _clip(a):
    return np.clip(a, 0.0, 1.0)


# --- species overlap (from the database) -------------------------------------------------------------------------
_overlap_cache: dict = {"t": 0.0, "key": None, "val": None}


def species_overlap_blocks(db: Session, env: Env) -> dict[tuple[int, int], int] | None:
    """{(block_i, block_j): n distinct species} from recent biodiversity observations; None if the DB has none at all."""
    b = env.bounds
    since = datetime.now(timezone.utc) - timedelta(days=OVERLAP_WINDOW_DAYS)
    total = db.execute(select(func.count()).select_from(BiodiversityObservation)).scalar_one()
    if total == 0:
        return None
    key = (total, round(b["lat_min"], 2))
    if _overlap_cache["key"] == key and time.monotonic() - _overlap_cache["t"] < 60:
        return _overlap_cache["val"]
    rows = db.execute(
        select(
            func.coalesce(BiodiversityObservation.species_name, BiodiversityObservation.scientific_name),
            BiodiversityObservation.latitude,
            BiodiversityObservation.longitude,
        ).where(
            BiodiversityObservation.timestamp >= since,
            BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]),
            BiodiversityObservation.longitude.between(b["lon_min"], b["lon_max"]),
        )
    ).all()
    blocks: dict[tuple[int, int], set] = {}
    for name, la, lo in rows:
        i = int(np.abs(env.lat - la).argmin())
        j = int(np.abs(env.lon - lo).argmin())
        blocks.setdefault((i // BLOCK, j // BLOCK), set()).add(name)
    val = {k: len(v) for k, v in blocks.items()}
    _overlap_cache.update(t=time.monotonic(), key=key, val=val)
    return val


# --- grids ---------------------------------------------------------------------------------------------------------
def current_anomaly(env: Env) -> np.ndarray:
    return env.z["latest_obs"] - env.z["latest_obs_climatology"]


def forecast_anomaly(env: Env) -> np.ndarray:
    return env.z["latest_forecast"] - env.z["latest_climatology"]


def factor_grids(env: Env, overlap: dict | None) -> dict:
    anom = _clip(np.abs(current_anomaly(env)) / 3.0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # land cells are all-NaN
        fc = _clip(np.nanmean(np.abs(forecast_anomaly(env)), axis=0) / 3.0)
    if env.hw is not None:
        persist = _clip(env.hw["run_len"].astype("float32") / 14.0)
    else:
        persist = None
    H, W = anom.shape
    if overlap is None:
        ov = None
    else:
        ov = np.zeros((H, W), dtype="float32")
        for (bi, bj), n in overlap.items():
            ov[bi * BLOCK:(bi + 1) * BLOCK, bj * BLOCK:(bj + 1) * BLOCK] = min(n / OVERLAP_SATURATION, 1.0)
    parts = {"anomaly": anom, "persistence": persist, "forecast": fc, "overlap": ov}
    w_total = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
    score = sum(WEIGHTS[k] * np.nan_to_num(v) for k, v in parts.items() if v is not None) / w_total
    score = np.where(env.z["ocean"] & ~np.isnan(env.z["latest_obs"]), score, np.nan)
    return {"factors": parts, "score": score.astype("float32"),
            "used": [k for k, v in parts.items() if v is not None]}


def score_to_levels(score: np.ndarray) -> np.ndarray:
    """0=LOW 1=MEDIUM 2=HIGH 3=CRITICAL (NaN -> -1)."""
    out = np.full(score.shape, -1, dtype="int8")
    ok = ~np.isnan(score)
    out[ok] = np.digitize(score[ok], [0.25, 0.5, 0.75]).astype("int8")
    return out


def cell_assessment(env: Env, i: int, j: int, overlap: dict | None, g: dict | None = None) -> dict:
    g = g or factor_grids(env, overlap)
    rows = []
    for k in ("anomaly", "persistence", "forecast", "overlap"):
        arr = g["factors"][k]
        if arr is None:
            rows.append({"factor": k, "value": None, "level": None, "weight": WEIGHTS[k], "available": False})
            continue
        v = float(arr[i, j])
        rows.append({"factor": k, "value": round(v, 3), "level": factor_level(v), "weight": WEIGHTS[k], "available": True})
    score = float(g["score"][i, j])
    anom = float(current_anomaly(env)[i, j])
    run = int(env.hw["run_len"][i, j]) if env.hw is not None else None
    fc = float(np.nanmean(forecast_anomaly(env)[:, i, j]))
    n_sp = None
    if overlap is not None:
        n_sp = overlap.get((i // BLOCK, j // BLOCK), 0)
    reasons = [f"Sea surface temperature is {anom:+.1f} degC relative to the 2012-2023 average for this day of the year."]
    if run:
        reasons.append(f"It has been above the seasonal 90th percentile for {run} days (a marine-heatwave run).")
    elif env.hw is not None:
        reasons.append("It is not currently in a marine-heatwave run (fewer than 5 consecutive days above the 90th percentile).")
    reasons.append(f"The model forecasts an average anomaly of {fc:+.1f} degC over the next 7 days.")
    if n_sp is None:
        reasons.append("No species-record data are loaded, so species overlap is not part of this score.")
    elif n_sp == 0:
        reasons.append("No OBIS species records are available in this 2x2 degree block.")
    else:
        reasons.append(f"{n_sp} species have OBIS records in this 2x2 degree block within the last {OVERLAP_WINDOW_DAYS} days.")
    return {"score": round(score, 3), "level": level_for(score), "factors": rows, "reasons": reasons,
            "n_species": n_sp, "used_factors": g["used"]}


# --- species-level risk ----------------------------------------------------------------------------------------------
def species_assessment(db: Session, env: Env, aphia_id: int, name: str) -> dict:
    """Potential exposure of a species' recent records (last 2 years, study region) to today's conditions."""
    b = env.bounds
    since = datetime.now(timezone.utc) - timedelta(days=OVERLAP_WINDOW_DAYS)
    rows = db.execute(
        select(BiodiversityObservation.latitude, BiodiversityObservation.longitude, BiodiversityObservation.timestamp)
        .where(
            (BiodiversityObservation.species_aphia_id == aphia_id) | (BiodiversityObservation.species_name == name)
            | (BiodiversityObservation.scientific_name == name),
            BiodiversityObservation.timestamp >= since,
            BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]),
            BiodiversityObservation.longitude.between(b["lon_min"], b["lon_max"]),
        )
    ).all()
    base = {"aphia_id": aphia_id, "scientific_name": name, "n_records": len(rows),
            "window_days": OVERLAP_WINDOW_DAYS, "methodology": METHODOLOGY["name"]}
    if not rows:
        return {**base, "available": False,
                "message": "No available observations for this species in the study region in the last two years, "
                           "so exposure cannot be assessed here."}
    cells: dict[tuple[int, int], int] = {}
    for la, lo, _ in rows:
        c = env.cell(la, lo)
        if c is None or not env.is_ocean(*c):
            continue
        cells[c] = cells.get(c, 0) + 1
    if not cells:
        return {**base, "available": False, "message": "Recorded positions fall outside the ocean grid cells covered by the model."}
    idx = np.array(list(cells.keys()))
    wts = np.array(list(cells.values()), dtype="float64")
    wts /= wts.sum()
    ii, jj = idx[:, 0], idx[:, 1]
    anom = current_anomaly(env)[ii, jj]
    f_anom = float(np.sum(wts * _clip(np.abs(anom) / 3.0)))
    f_persist = None if env.hw is None else float(np.sum(wts * _clip(env.hw["run_len"][ii, jj] / 14.0)))
    fc_anom = np.nanmean(np.abs(forecast_anomaly(env)[:, ii, jj]), axis=0)
    f_fc = float(np.sum(wts * _clip(fc_anom / 3.0)))
    exposed_share = float(np.sum(wts * (np.abs(anom) >= 1.0)))
    f_overlap = exposed_share
    parts = {"anomaly": f_anom, "persistence": f_persist, "forecast": f_fc, "overlap": f_overlap}
    wt = sum(WEIGHTS[k] for k, v in parts.items() if v is not None)
    score = sum(WEIGHTS[k] * v for k, v in parts.items() if v is not None) / wt
    factors = [{"factor": k, "value": None if v is None else round(v, 3),
                "level": None if v is None else factor_level(v), "weight": WEIGHTS[k], "available": v is not None}
               for k, v in parts.items()]
    share_mhw = None if env.hw is None else float(np.sum(wts * env.hw["active"][ii, jj]))
    reasons = [
        f"{len(rows)} OBIS records from the last {OVERLAP_WINDOW_DAYS} days fall in {len(cells)} grid cells of the study region.",
        f"Weighted by record count, SST at those locations is {float(np.sum(wts * anom)):+.1f} degC from the 2012-2023 average today.",
        f"{exposed_share * 100:.0f}% of the recorded positions are in cells at least 1 degC away from normal.",
    ]
    if share_mhw is not None:
        reasons.append(f"{share_mhw * 100:.0f}% of the recorded positions are inside an active marine-heatwave area.")
    reasons.append(f"The 7-day forecast keeps an average |anomaly| of {float(np.sum(wts * fc_anom)):.1f} degC at those locations.")
    exposed_cells = int((np.abs(anom) >= 1.0).sum())
    signed_fc = np.nanmean(forecast_anomaly(env)[:, ii, jj], axis=0)
    hw_cells = None if env.hw is None else int(env.hw["active"][ii, jj].sum())
    hw_runs = None if env.hw is None else env.hw["run_len"][ii, jj][env.hw["active"][ii, jj]]
    recent_cut = max(ts for _, _, ts in rows) - timedelta(days=90)
    out = {**base, "available": True, "score": round(score, 3), "level": level_for(score), "factors": factors,
           "reasons": reasons, "n_cells": len(cells), "exposed_share": round(exposed_share, 3),
           "heatwave_share": None if share_mhw is None else round(share_mhw, 3),
           "mean_anomaly_c": round(float(np.sum(wts * anom)), 2),
           "max_anomaly_c": round(float(anom[np.abs(anom).argmax()]), 2),
           "observed_locations": len(cells), "overlapping_locations": exposed_cells,
           "exposure_pct_locations": round(100.0 * exposed_cells / len(cells), 1),
           "heatwave_locations": hw_cells,
           "heatwave_days_mean": None if hw_runs is None or hw_runs.size == 0 else round(float(hw_runs.mean()), 1),
           "heatwave_days_max": None if hw_runs is None or hw_runs.size == 0 else int(hw_runs.max()),
           "forecast_exposure": factor_level(f_fc), "forecast_mean_anomaly_c": round(float(np.sum(wts * signed_fc)), 2),
           "recent_records_90d": sum(1 for _, _, ts in rows if ts >= recent_cut),
           "latest_record": max(ts for _, _, ts in rows).astimezone(timezone.utc).date().isoformat()}
    # thermal range at the record locations/dates from the stored 2-year SST history (derived from NOAA OISST)
    if env.hist is not None:
        dates = env.hist["dates"]
        dmap = {str(d): k for k, d in enumerate(dates)}
        vals = []
        for la, lo, ts in rows:
            c = env.cell(la, lo)
            k = dmap.get(ts.astimezone(timezone.utc).strftime("%Y-%m-%d"))
            if c is None or k is None:
                continue
            raw = int(env.hist["sst_c"][k, c[0], c[1]])
            if raw != -32768:
                vals.append(raw / 100.0)
        if len(vals) >= 5:
            q = np.percentile(vals, [10, 50, 90])
            out["thermal_range_c"] = {"p10": round(float(q[0]), 1), "median": round(float(q[1]), 1),
                                      "p90": round(float(q[2]), 1), "n": len(vals)}
    return out
