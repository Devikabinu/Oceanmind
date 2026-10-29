"""Project environmental / ecological risk indicator (explainable, rule-based).

NOT an established published index. It is a transparent weighted combination of four 0-1 factors, each defined below,
intended to rank *monitoring priority* / *potential exposure*. It does not prove biological harm.
"""
from __future__ import annotations

import time
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np
from sqlalchemy import func, or_, select
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
        "anomaly": "Size of today's SST anomaly (observed SST minus the baseline daily climatology of the dataset): |anomaly| / 3 degC, capped at 1.",
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


# --- dataset boundary ---------------------------------------------------------------------------------------------
# The risk methodology (weights, factor definitions, levels) is the same for every dataset. A dataset only supplies *inputs*: the current SST
# anomaly grid, which cells are land / missing, and, where they exist, heatwave persistence and a forecast. A factor a dataset cannot supply is
# None with a reason; it is dropped from the score (the weights of the remaining factors are renormalised, as the methodology always did when a
# factor was absent) and is never treated as zero.
ASSESSED, INSUFFICIENT, UNAVAILABLE, LAND, OUTSIDE = 0, 1, 2, 3, 4
STATUS_NAMES = {ASSESSED: "assessed", INSUFFICIENT: "insufficient_data", UNAVAILABLE: "unavailable", LAND: "land", OUTSIDE: "outside_region"}
LEGACY_DATASET = "ne_pacific"


@dataclass
class RiskInputs:
    dataset: str
    lat: np.ndarray
    lon: np.ndarray
    res: float
    bounds: dict
    date: str
    anomaly: np.ndarray                              # current SST anomaly, NaN where it cannot be computed
    state: np.ndarray                                # int8 per cell: ASSESSED / INSUFFICIENT / UNAVAILABLE / LAND
    persistence_days: np.ndarray | None              # marine-heatwave run length, None when the dataset has no heatwave state
    forecast_anomaly: np.ndarray | None              # (n, H, W), None when the dataset has no forecast
    unavailable: dict = field(default_factory=dict)  # factor -> why this dataset cannot supply it
    notes: dict = field(default_factory=dict)        # factor -> provenance caveat shown next to an available factor
    species_sampled: bool = True                     # True: OBIS records were gathered for this domain, so an empty block counts as "none recorded"
    source: dict = field(default_factory=dict)
    area_name: str = "the study region"
    hw: dict | None = None
    hist: dict | None = None
    cell_fn: Callable | None = None
    lon_origin: float = 0.0
    baseline: list | None = None                     # [start, end] of the climatology the anomaly is measured against
    forecast_issued: str | None = None               # observation date the forecast was issued from (None when there is none)
    forecast_dates: list | None = None
    heatwave_date: str | None = None
    species_latest: str | None = None

    @property
    def block(self) -> int:
        return max(1, int(round(2.0 / self.res)))            # 2 x 2 degree species-overlap block, in cells

    def cell(self, lat: float, lon: float):
        return self.cell_fn(lat, lon)

    def is_ocean(self, i: int, j: int) -> bool:
        return bool(np.isfinite(self.anomaly[i, j]))

    def axis_lon(self, lon):
        return self.lon_origin + np.mod(np.asarray(lon, dtype="float64") - self.lon_origin, 360.0)


def legacy_inputs(env: Env) -> RiskInputs:
    """The NE Pacific dashboard export as risk inputs (cached on the Env object)."""
    cached = getattr(env, "_risk_inputs", None)
    if cached is not None:
        return cached
    anom = current_anomaly(env)
    ocean = env.z["ocean"] & ~np.isnan(env.z["latest_obs"])
    state = np.where(env.z["ocean"], np.where(ocean, ASSESSED, UNAVAILABLE), LAND).astype("int8")
    inp = RiskInputs(
        dataset=LEGACY_DATASET, lat=env.lat, lon=env.lon, res=env.res, bounds=env.bounds, date=env.info["latest"]["observed_date"],
        anomaly=np.where(ocean, anom, np.nan), state=state,
        persistence_days=None if env.hw is None else env.hw["run_len"].astype("float32"),
        forecast_anomaly=forecast_anomaly(env), species_sampled=True,
        source={"provider_id": "noaa_oisst_v2.1_processed", "is_observational": True, "description": "NOAA OISST v2.1 (processed) with the project ConvLSTM forecast"},
        hw=env.hw, hist=env.hist, cell_fn=env.cell, lon_origin=float(env.lon.min()) - env.res / 2, baseline=["2012-01-01", "2023-12-31"],
        forecast_issued=env.info["latest"]["observed_date"], forecast_dates=env.info["latest"]["target_dates"],
        heatwave_date=None if env.hwinfo is None else env.hwinfo.get("latest_date"),
    )
    if env.hw is None:
        inp.unavailable["persistence"] = "marine-heatwave state not found; re-run the dashboard export"
    try:
        env._risk_inputs = inp  # type: ignore[attr-defined]
    except AttributeError:
        pass
    return inp


def as_inputs(x) -> RiskInputs:
    return x if isinstance(x, RiskInputs) else legacy_inputs(x)


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


def _lon_clause(b: dict, origin: float):
    """SQL longitude filter for a domain on a continuous axis (e.g. 100..290 east): records are stored in -180..180."""
    lo, hi = b["lon_min"], b["lon_max"]
    if hi <= 180:
        return BiodiversityObservation.longitude.between(lo, hi)
    return or_(BiodiversityObservation.longitude.between(lo, 180.0), BiodiversityObservation.longitude.between(-180.0, hi - 360.0))


def species_overlap_blocks(db: Session, env) -> dict[tuple[int, int], int] | None:
    """{(block_i, block_j): n distinct species} from recent biodiversity observations; None if the DB has none at all.
    `env` is the NE Pacific Env or a RiskInputs for another dataset."""
    inp = as_inputs(env)
    b = inp.bounds
    since = datetime.now(timezone.utc) - timedelta(days=OVERLAP_WINDOW_DAYS)
    total = db.execute(select(func.count()).select_from(BiodiversityObservation)).scalar_one()
    if total == 0:
        return None
    key = (inp.dataset, total, round(b["lat_min"], 2), round(b["lon_min"], 2))
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
            _lon_clause(b, inp.lon_origin),
        )
    ).all()
    blocks: dict[tuple[int, int], set] = {}
    B = inp.block
    lon_axis = inp.axis_lon(inp.lon)
    for name, la, lo in rows:
        i = int(np.abs(inp.lat - la).argmin())
        j = int(np.abs(lon_axis - float(inp.axis_lon(lo))).argmin())
        blocks.setdefault((i // B, j // B), set()).add(name)
    val = {k: len(v) for k, v in blocks.items()}
    _overlap_cache.update(t=time.monotonic(), key=key, val=val)
    return val


# --- grids ---------------------------------------------------------------------------------------------------------
def current_anomaly(env: Env) -> np.ndarray:
    return env.z["latest_obs"] - env.z["latest_obs_climatology"]


def forecast_anomaly(env: Env) -> np.ndarray:
    return env.z["latest_forecast"] - env.z["latest_climatology"]


BIO_STATES = ("observed", "none_recorded", "insufficient_coverage", "unavailable", "nearby")
NEARBY_REACH_DEG = 10.0        # an unsampled 2x2 degree block borrows the nearest sampled block within this distance, and says so


def factor_grids(env, overlap: dict | None) -> dict:
    """Factor grids and score for a dataset (NE Pacific Env or RiskInputs). Per cell, factors that are missing are left out and the weights of
    the others renormalised; a cell with no anomaly has no score at all."""
    inp = as_inputs(env)
    anom = _clip(np.abs(inp.anomaly) / 3.0)
    H, W = anom.shape
    if inp.forecast_anomaly is not None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # land cells are all-NaN
            fc = _clip(np.nanmean(np.abs(inp.forecast_anomaly), axis=0) / 3.0)
    else:
        fc = None
    persist = None if inp.persistence_days is None else _clip(inp.persistence_days / 14.0)
    B = inp.block
    bio = np.full((H, W), 3, dtype="int8")                   # unavailable (no biodiversity data loaded)
    if overlap is None:
        ov = None
    else:
        ov = np.full((H, W), np.nan, dtype="float32")        # NaN = no biodiversity evidence for this cell (never 0 unless records were gathered here)
        bio[:] = 1 if inp.species_sampled else 2
        if inp.species_sampled:
            ov[:] = 0.0
        for (bi, bj), n in overlap.items():
            ov[bi * B:(bi + 1) * B, bj * B:(bj + 1) * B] = min(n / OVERLAP_SATURATION, 1.0)
            bio[bi * B:(bi + 1) * B, bj * B:(bj + 1) * B] = 0
    regional: dict = {}
    if overlap and ov is not None and not inp.species_sampled:                            # nearby records: the nearest sampled block within NEARBY_REACH_DEG, never zero
        from scipy import ndimage
        nbi, nbj = -(-H // B), -(-W // B)
        grid = np.full((nbi, nbj), np.nan)
        for (bi, bj), n in overlap.items():
            if bi < nbi and bj < nbj:
                grid[bi, bj] = n
        sampled = np.isfinite(grid)
        if sampled.any() and not sampled.all():
            dist, (ii, jj) = ndimage.distance_transform_edt(~sampled, return_indices=True)
            for bi, bj in zip(*np.where(~sampled & (dist * B * inp.res <= NEARBY_REACH_DEG))):
                n = int(grid[ii[bi, bj], jj[bi, bj]])
                regional[(int(bi), int(bj))] = (n, round(float(dist[bi, bj] * B * inp.res), 1))
                ov[bi * B:(bi + 1) * B, bj * B:(bj + 1) * B] = min(n / OVERLAP_SATURATION, 1.0)
                bio[bi * B:(bi + 1) * B, bj * B:(bj + 1) * B] = 4
    parts = {"anomaly": anom, "persistence": persist, "forecast": fc, "overlap": ov}
    num = np.zeros((H, W), dtype="float64")
    den = np.zeros((H, W), dtype="float64")
    for k, v in parts.items():
        if v is None:
            continue
        ok = np.isfinite(v)
        num += np.where(ok, WEIGHTS[k] * np.nan_to_num(v), 0.0)
        den += np.where(ok, WEIGHTS[k], 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        score = num / den
    scored = np.isfinite(anom) & (inp.state == ASSESSED)
    score = np.where(scored & (den > 0), score, np.nan)
    return {"factors": parts, "score": score.astype("float32"), "used": [k for k, v in parts.items() if v is not None],
            "completeness": np.where(scored, den / sum(WEIGHTS.values()), np.nan).astype("float32"), "bio": bio, "regional": regional}


def score_to_levels(score: np.ndarray) -> np.ndarray:
    """0=LOW 1=MEDIUM 2=HIGH 3=CRITICAL (NaN -> -1)."""
    out = np.full(score.shape, -1, dtype="int8")
    ok = ~np.isnan(score)
    out[ok] = np.digitize(score[ok], [0.25, 0.5, 0.75]).astype("int8")
    return out


SATURATION = {"anomaly": 3.0, "persistence": 14.0, "forecast": 3.0, "overlap": float(OVERLAP_SATURATION)}      # raw value at which a factor reaches 1.0
NORMALIZATION = {"anomaly": "factor = min(|anomaly| / 3 °C, 1)", "persistence": "factor = min(heatwave run length / 14 days, 1)",
                 "forecast": "factor = min(mean |forecast anomaly| over the 7 days / 3 °C, 1)", "overlap": f"factor = min(distinct species in the 2x2 degree block / {int(OVERLAP_SATURATION)}, 1)"}
RAW_UNIT = {"anomaly": "°C", "persistence": "days", "forecast": "°C", "overlap": "species"}
MISSING_INPUT = {"persistence": "marine-heatwave results for this date", "forecast": "a forecast issued from this date", "overlap": "stored biodiversity records in this 2x2 degree block"}


def baseline_text(inp: "RiskInputs") -> str:
    return f"the {inp.baseline[0][:4]}-{inp.baseline[1][:4]} average" if inp.baseline else "the dataset's climatological average"


def cell_assessment(env, i: int, j: int, overlap: dict | None, g: dict | None = None) -> dict:
    """The risk of one cell with every step of its calculation. For each factor: the raw value it is made from, the saturation point, the factor (0-1), its nominal and effective
    weight (renormalised over the factors that are present), its contribution in score points, and a `status`:
      contributing  - evidence is present and the factor is at least LOW-to-MEDIUM sized
      below_threshold - evidence is present and the factor is small (< 0.33): it is in the score, at a low value; this is NOT 'insufficient evidence'
      incomplete    - evidence is present but covers only part of what is expected (e.g. a forecast for fewer than all 7 days); it is used as far as it goes
      unavailable   - the input does not exist (for this cell or date): `missing_input` says which one and `reason` why; the factor is left out and is never treated as zero.
    The score is the sum of the contributions: sum(weight_k * factor_k) / sum(weight_k over present factors)."""
    inp = as_inputs(env)
    g = g or factor_grids(inp, overlap)
    anom = float(inp.anomaly[i, j])
    run = None if inp.persistence_days is None else int(inp.persistence_days[i, j])
    fcs = None if inp.forecast_anomaly is None else inp.forecast_anomaly[:, i, j]
    fc_days = None if fcs is None else int(np.isfinite(fcs).sum())
    fc_mean = None if fcs is None or not fc_days else float(np.nanmean(fcs))
    fc_abs = None if fcs is None or not fc_days else float(np.nanmean(np.abs(fcs)))
    blk = (i // inp.block, j // inp.block)
    near = (g.get("regional") or {}).get(blk)
    n_sp = None if overlap is None else (near[0] if near and blk not in overlap else overlap.get(blk, 0))
    raw = {"anomaly": (anom, abs(anom) if np.isfinite(anom) else None), "persistence": (run, run), "forecast": (fc_mean, fc_abs), "overlap": (n_sp, n_sp)}
    present = [k for k in ("anomaly", "persistence", "forecast", "overlap") if g["factors"][k] is not None and np.isfinite(g["factors"][k][i, j])]
    den = sum(WEIGHTS[k] for k in present)
    rows = []
    for k in ("anomaly", "persistence", "forecast", "overlap"):
        arr = g["factors"][k]
        v = None if arr is None else float(arr[i, j])
        shown, magnitude = raw[k]
        if v is None or not np.isfinite(v):
            reason = inp.unavailable.get(k) or ("no stored biodiversity records in this 2x2 degree block: limited coverage, not evidence that no animals are present" if k == "overlap" else "no data for this cell")
            rows.append({"factor": k, "value": None, "level": None, "weight": WEIGHTS[k], "nominal_weight": WEIGHTS[k], "effective_weight": None, "contribution": None, "available": False,
                         "status": "unavailable", "missing_input": MISSING_INPUT.get(k, "an SST anomaly for this cell"), "reason": reason, "raw": None, "raw_unit": RAW_UNIT[k],
                         "saturation_at": SATURATION[k], "saturated": None, "ratio": None, "normalization": NORMALIZATION[k]})
            continue
        status = "incomplete" if (k == "forecast" and fc_days is not None and inp.forecast_anomaly is not None and fc_days < inp.forecast_anomaly.shape[0]) else "below_threshold" if factor_level(v) == "LOW" else "contributing"
        eff = WEIGHTS[k] / den
        rows.append({"factor": k, "value": round(v, 3), "value_exact": v, "level": factor_level(v), "weight": WEIGHTS[k], "nominal_weight": WEIGHTS[k], "effective_weight": round(eff, 4),
                     "contribution": round(eff * v, 4), "available": True, "status": status, "raw": None if shown is None else round(float(shown), 2), "raw_magnitude": None if magnitude is None else round(float(magnitude), 2),
                     "raw_unit": RAW_UNIT[k], "saturation_at": SATURATION[k], "saturated": bool(magnitude is not None and magnitude >= SATURATION[k]),
                     "ratio": None if magnitude is None else round(float(magnitude) / SATURATION[k], 2), "days_with_data": fc_days if k == "forecast" else None, "normalization": NORMALIZATION[k],
                     **({"scope": "nearby", "distance_deg": near[1]} if k == "overlap" and near and blk not in overlap else {}),
                     **({"note": inp.notes[k]} if k in inp.notes else {})})
    score = float(g["score"][i, j])
    st = int(inp.state[i, j])
    out_state = (INSUFFICIENT if st == ASSESSED else st) if not np.isfinite(score) else ASSESSED
    base = baseline_text(inp)
    reasons = [f"Sea surface temperature is {anom:+.1f} degC relative to {base} for this day of the year."] if np.isfinite(anom) else []
    if run:
        reasons.append(f"It has been above the seasonal 90th percentile for {run} days (a marine-heatwave run).")
    elif inp.persistence_days is not None:
        reasons.append("It is not currently in a marine-heatwave run (fewer than 5 consecutive days above the 90th percentile).")
    else:
        reasons.append(f"Heatwave persistence is not available for this dataset: {inp.unavailable.get('persistence', 'no heatwave state')}.")
    if fc_mean is not None:
        reasons.append(f"The model forecasts an average anomaly of {fc_mean:+.1f} degC (average size {fc_abs:.1f} degC) over the next {fc_days} days.")
    else:
        reasons.append(f"Forecast exposure is not available for this dataset: {inp.unavailable.get('forecast', 'no forecast')}.")
    bio_state = BIO_STATES[int(g["bio"][i, j])]
    if bio_state == "nearby":
        reasons.append(f"{n_sp} distinct species have OBIS records in the nearest sampled 2x2 block, about {near[1]:g}° away (nearby records, not records at this cell).")
    elif n_sp is None:
        reasons.append("No species-record data are loaded, so species overlap is not part of this score.")
    elif bio_state == "insufficient_coverage":
        reasons.append("No OBIS species records exist in this 2x2 degree block; that is limited biodiversity coverage, not evidence that no animals are present, so species overlap is not part of this score.")
    elif n_sp == 0:
        reasons.append("No OBIS species records are available in this 2x2 degree block.")
    else:
        reasons.append(f"{n_sp} distinct species have OBIS records in this 2x2 degree block within the last {OVERLAP_WINDOW_DAYS} days.")
    comp = float(g["completeness"][i, j]) if "completeness" in g and np.isfinite(g["completeness"][i, j]) else None
    used_rows = [r for r in rows if r["available"]]
    return {"score": round(score, 3) if np.isfinite(score) else None, "score_exact": score if np.isfinite(score) else None, "level": level_for(score) if np.isfinite(score) else None,
            "status": STATUS_NAMES[out_state], "factors": rows, "reasons": reasons,
            "score_breakdown": {"terms": [{"factor": r["factor"], "contribution": r["contribution"]} for r in used_rows], "sum": round(sum(r["contribution"] for r in used_rows), 3) if used_rows else None,
                                "denominator_weight": round(den, 3), "formula": "score = sum(nominal weight x factor) / sum(nominal weights of the factors that are present)"},
            "n_species": n_sp, "biodiversity_evidence": bio_state, "evidence_completeness": None if comp is None else round(comp, 3),
            "evidence": {"anomaly_c": round(anom, 2) if np.isfinite(anom) else None, "heatwave_run_days": run,
                         "forecast_mean_anomaly_c": None if fc_mean is None else round(fc_mean, 2), "forecast_mean_abs_anomaly_c": None if fc_abs is None else round(fc_abs, 2),
                         "forecast_days": fc_days, "n_species": n_sp, "date": inp.date, "baseline": inp.baseline},
            "unavailable_factors": {k: inp.unavailable.get(k, "no data for this cell") for k in ("persistence", "forecast") if g["factors"][k] is None},
            "used_factors": g["used"]}


# --- species-level risk ----------------------------------------------------------------------------------------------
def species_assessment(db: Session, env, aphia_id: int, name: str) -> dict:
    """Potential exposure of a species' recent records (last 2 years, inside the dataset domain) to today's conditions.
    `env` is the NE Pacific Env or a RiskInputs; factors the dataset cannot supply are dropped, never zero."""
    env = as_inputs(env)
    b = env.bounds
    since = datetime.now(timezone.utc) - timedelta(days=OVERLAP_WINDOW_DAYS)
    rows = db.execute(
        select(BiodiversityObservation.latitude, BiodiversityObservation.longitude, BiodiversityObservation.timestamp)
        .where(
            (BiodiversityObservation.species_aphia_id == aphia_id) | (BiodiversityObservation.species_name == name)
            | (BiodiversityObservation.scientific_name == name),
            BiodiversityObservation.timestamp >= since,
            BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]),
            _lon_clause(b, env.lon_origin),
        )
    ).all()
    base = {"aphia_id": aphia_id, "scientific_name": name, "n_records": len(rows),
            "window_days": OVERLAP_WINDOW_DAYS, "methodology": METHODOLOGY["name"], "dataset": env.dataset}
    if not rows:
        return {**base, "available": False,
                "status": "insufficient_data",
                "message": f"No available observations for this species in {env.area_name} in the last two years, "
                           "so exposure cannot be assessed here. (No observations is not the same as no animals.)"}
    cells: dict[tuple[int, int], int] = {}
    for la, lo, _ in rows:
        c = env.cell(la, lo)
        if c is None or not env.is_ocean(*c):
            continue
        cells[c] = cells.get(c, 0) + 1
    if not cells:
        return {**base, "available": False, "status": "insufficient_data",
                "message": "Recorded positions fall outside the ocean grid cells that have data in this dataset."}
    idx = np.array(list(cells.keys()))
    wts = np.array(list(cells.values()), dtype="float64")
    wts /= wts.sum()
    ii, jj = idx[:, 0], idx[:, 1]
    anom = env.anomaly[ii, jj]
    f_anom = float(np.sum(wts * _clip(np.abs(anom) / 3.0)))
    f_persist = None if env.persistence_days is None else float(np.sum(wts * _clip(env.persistence_days[ii, jj] / 14.0)))
    if env.forecast_anomaly is not None:
        fc_anom = np.nanmean(np.abs(env.forecast_anomaly[:, ii, jj]), axis=0)
        f_fc = float(np.sum(wts * _clip(fc_anom / 3.0)))
    else:
        fc_anom, f_fc = None, None
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
        f"{len(rows)} OBIS records from the last {OVERLAP_WINDOW_DAYS} days fall in {len(cells)} grid cells of {env.area_name}.",
        f"Weighted by record count, SST at those locations is {float(np.sum(wts * anom)):+.1f} degC from {baseline_text(env)} today.",
        f"{exposed_share * 100:.0f}% of the recorded positions are in cells at least 1 degC away from normal.",
    ]
    if share_mhw is not None:
        reasons.append(f"{share_mhw * 100:.0f}% of the recorded positions are inside an active marine-heatwave area.")
    if fc_anom is not None:
        reasons.append(f"The 7-day forecast keeps an average |anomaly| of {float(np.sum(wts * fc_anom)):.1f} degC at those locations.")
    else:
        reasons.append(f"Forecast exposure is not available for this dataset: {env.unavailable.get('forecast', 'no forecast')}.")
    if env.persistence_days is None:
        reasons.append(f"Heatwave persistence is not available for this dataset: {env.unavailable.get('persistence', 'no heatwave state')}.")
    exposed_cells = int((np.abs(anom) >= 1.0).sum())
    signed_fc = None if env.forecast_anomaly is None else np.nanmean(env.forecast_anomaly[:, ii, jj], axis=0)
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
           "forecast_exposure": None if f_fc is None else factor_level(f_fc),
           "forecast_mean_anomaly_c": None if signed_fc is None else round(float(np.sum(wts * signed_fc)), 2),
           "status": "assessed", "evidence_completeness": round(wt / sum(WEIGHTS.values()), 3),
           "unavailable_factors": {k: env.unavailable.get(k, "not available for this dataset") for k, v in parts.items() if v is None},
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


# --- other datasets (Pacific-wide processed environment) ---------------------------------------------------------------
PACIFIC_UNAVAILABLE = {
    "persistence": "marine-heatwave results have not been built for this dataset, so heatwave persistence is not available (it is not treated as zero)",
    "forecast": "no forecast has been exported for this dataset, so forecast exposure is not available (it is not treated as zero)",
}
_inputs_cache: dict = {}


def inputs_for(dataset: str | None, date=None) -> RiskInputs:
    """Risk inputs for a dataset id. The ONE place that knows how each dataset feeds the methodology."""
    from app.services import environment_store as es
    ds = es.resolve_dataset_id(dataset) if dataset else LEGACY_DATASET
    if ds == LEGACY_DATASET:
        from app.services.environment import env as load_env
        return legacy_inputs(load_env())
    store = es.get_store(ds)
    t = store.resolve_date(date)
    from app.services import heatwave_service as hws
    hw = hws.state_for(ds)
    fmt = (store.ref.path / "model" / "dashboard" / "snapshot.npz")
    key = (ds, str(t.date()), (store.ref.path / "meta.json").stat().st_mtime, None if hw is None else id(hw.state), fmt.stat().st_mtime if fmt.exists() else None)
    if key in _inputs_cache:
        return _inputs_cache[key]
    anom, anom_status, _ = store.native_layer("anomaly", t)
    _, sst_status, _ = store.native_layer("sst", t)
    state = np.where(sst_status == es.LAND, LAND, np.where(sst_status != es.VALID, UNAVAILABLE, np.where(np.isfinite(anom), ASSESSED, INSUFFICIENT))).astype("int8")
    ext = store.extent

    def cell_fn(lat: float, lon: float):
        a = float(store.lon[0]) - store.res / 2 + float(np.mod(lon - (float(store.lon[0]) - store.res / 2), 360.0))
        if not (ext["lat_min"] <= lat <= ext["lat_max"] and a <= ext["lon_max"]):
            return None
        return (min(int((lat - ext["lat_min"]) // store.res), len(store.lat) - 1), min(int((a - ext["lon_min"]) // store.res), len(store.lon) - 1))

    unavailable = dict(PACIFIC_UNAVAILABLE)
    notes: dict = {}
    forecast_anom = None
    f_issued = f_dates = None
    try:
        from app.services import forecast_store
        fsnap, finfo, fmetrics, forigin = forecast_store.load(ds)
        f_issued, f_dates = finfo["latest"]["observed_date"], finfo["latest"]["target_dates"]
        if finfo["latest"]["observed_date"] == str(t.date()) and fsnap["latest_forecast"].shape[1:] == anom.shape:
            forecast_anom = fsnap["latest_forecast"] - fsnap["latest_climatology"]
            unavailable.pop("forecast")
            beats = fmetrics is not None and all(x > 0 for x in fmetrics["baselines"]["convlstm"]["mae_skill_vs_persistence"])
            notes["forecast"] = (f"ConvLSTM weights trained on {forigin['trained_on']}, not retrained for this dataset" if forigin else "ConvLSTM forecast")
            notes["forecast"] += "; measured on this dataset it " + ("beat persistence" if beats else "did not beat persistence") if fmetrics else "; not evaluated on this dataset"
        elif finfo["latest"]["observed_date"] != str(t.date()):
            unavailable["forecast"] = (f"the forecast was issued from {finfo['latest']['observed_date']}, not {t.date()}, so forecast exposure is not available (it is not treated as zero)")
    except Exception:  # no forecast exported for this dataset: stays unavailable with the default reason
        pass
    persistence = hw_state = None
    if hw is not None and hw.state is not None and hw.state["run_len"].shape == anom.shape:
        if hw.info["latest_date"] == str(t.date()):
            persistence, hw_state = hw.state["run_len"].astype("float32"), hw.state       # the same run lengths the heatwave detector produced
            unavailable.pop("persistence")
        else:
            unavailable["persistence"] = (f"heatwave results exist only for the dataset's latest date ({hw.info['latest_date']}), not {t.date()}, "
                                          "so heatwave persistence is not available (it is not treated as zero)")
    inp = RiskInputs(
        dataset=ds, lat=store.lat, lon=store.lon, res=store.res, bounds=ext, date=str(t.date()), anomaly=anom, state=state,
        persistence_days=persistence, hw=hw_state, forecast_anomaly=forecast_anom, unavailable=unavailable, notes=notes,
        species_sampled=False, source=dict(store.source), area_name="the Pacific dataset domain", cell_fn=cell_fn,
        lon_origin=float(store.lon[0]) - store.res / 2, baseline=store.train_period, forecast_issued=f_issued, forecast_dates=f_dates,
        heatwave_date=None if hw is None else hw.info.get("latest_date"),
    )
    if len(_inputs_cache) > 6:
        _inputs_cache.clear()
    _inputs_cache[key] = inp
    return inp


def dataset_capabilities(dataset: str | None) -> dict:
    inp = inputs_for(dataset)
    return {"dataset": inp.dataset, "date": inp.date, "source": inp.source,
            "factors_available": [k for k in WEIGHTS if k not in inp.unavailable and (k != "persistence" or inp.persistence_days is not None)
                                  and (k != "forecast" or inp.forecast_anomaly is not None)],
            "factors_unavailable": {k: v for k, v in inp.unavailable.items()},
            "species_overlap_policy": "an empty 2x2 degree block means no records were gathered there (counted as zero overlap)" if inp.species_sampled
            else "an empty 2x2 degree block means limited biodiversity coverage; overlap is left out of that cell's score rather than set to zero"}


def map_levels(score: np.ndarray) -> np.ndarray:
    return score_to_levels(score)


def risk_map(db: Session, dataset: str | None, region: str | None, date, max_cells: int = 30000) -> dict:
    """Risk grid for a dataset, restricted to a region and aggregated to a map-sized grid. Cell states: assessed / insufficient / unavailable / land / outside."""
    from app.services import environment_store as es
    from app.services import geo_regions as geo
    inp = inputs_for(dataset, date)
    overlap = species_overlap_blocks(db, inp)
    g = factor_grids(inp, overlap)
    reg = geo.get_region(region or "pacific")
    # region masks work on any longitude axis, so they apply unchanged to the Pacific grid and to the NE Pacific grid
    mask = geo.region_mask(reg, inp.lat, inp.lon)
    if not mask.any():
        raise ValueError("The region does not overlap this dataset")
    rows = np.arange(np.flatnonzero(mask.any(axis=1)).min(), np.flatnonzero(mask.any(axis=1)).max() + 1)
    cols = np.flatnonzero(mask.any(axis=0))
    ordered = cols[np.argsort(geo.to_east(inp.lon[cols]), kind="stable")]
    sel = np.ix_(rows, ordered)
    score, state, m = g["score"][sel].copy(), inp.state[sel].copy(), mask[sel]
    state = np.where(m, state, OUTSIDE).astype("int8")
    state = np.where(m & (state == ASSESSED) & ~np.isfinite(score), INSUFFICIENT, state).astype("int8")
    score[~m] = np.nan
    lat_sel, lon_sel = inp.lat[rows], inp.lon[ordered]
    if not np.all(np.diff(lon_sel) > 0):
        lon_sel = geo.to_east(lon_sel)
    counts = {STATUS_NAMES[k]: int(((state == k) & m).sum()) for k in (ASSESSED, INSUFFICIENT, UNAVAILABLE, LAND)}
    f = 1
    if score.size > max_cells:
        f = int(np.ceil(np.sqrt(score.size / max_cells)))
        score, state, lat_sel, lon_sel = _aggregate(score, state, lat_sel, lon_sel, f)
    levels = score_to_levels(score)
    fin = score[np.isfinite(score)]
    ok = lambda x: None if not np.isfinite(x) else round(float(x), 3)  # noqa: E731
    return {
        "dataset": inp.dataset, "date": inp.date, "region": {"id": reg.id, "name": reg.name},
        "layer": "risk", "label": "Project environmental risk indicator", "kind": "derived", "unit": "score 0-1", "diverging": False,
        "methodology": METHODOLOGY["name"], "weights": WEIGHTS, "source": inp.source, "capabilities": dataset_capabilities(inp.dataset),
        "factors_used": g["used"], "factors_unavailable": dict(inp.unavailable),
        "lat": [round(float(x), 4) for x in lat_sel], "lon": [round(float(x), 4) for x in lon_sel],
        "values": [[ok(x) for x in row] for row in score], "levels": levels.tolist(), "status": state.tolist(),
        "status_legend": {"0": "assessed", "1": "not assessed (no SST anomaly)", "2": "unavailable (no environmental data this day)", "3": "land",
                          "4": "outside the selected region"},
        "level_legend": {"-1": "no score", "0": "LOW", "1": "MEDIUM", "2": "HIGH", "3": "CRITICAL"},
        "min": None if not fin.size else round(float(fin.min()), 3), "max": None if not fin.size else round(float(fin.max()), 3),
        "counts": counts, "downsample_factor": f, "coverage_note": "A score uses only the factors available for this dataset; see factors_unavailable.",
    }


def _aggregate(score, state, lat, lon, f):
    H, W = score.shape
    ph, pw = (-H) % f, (-W) % f
    v = np.pad(score, ((0, ph), (0, pw)), constant_values=np.nan).reshape((H + ph) // f, f, (W + pw) // f, f)
    s = np.pad(state, ((0, ph), (0, pw)), constant_values=OUTSIDE).reshape(v.shape)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        mean = np.nanmean(v, axis=(1, 3))
        la = np.nanmean(np.pad(lat, (0, ph), constant_values=np.nan).reshape(-1, f), axis=1)
        lo = np.nanmean(np.pad(lon, (0, pw), constant_values=np.nan).reshape(-1, f), axis=1)
    st = np.full(mean.shape, OUTSIDE, dtype="int8")
    for code in (LAND, UNAVAILABLE, INSUFFICIENT, ASSESSED):          # later codes win: assessed > insufficient > unavailable > land
        st = np.where((s == code).any(axis=(1, 3)), code, st)
    st = np.where(st == ASSESSED, np.where(np.isfinite(mean), ASSESSED, INSUFFICIENT), st).astype("int8")
    return mean.astype("float32"), st, la, lo
