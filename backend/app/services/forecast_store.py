"""Forecast results of a dataset other than the NE Pacific (e.g. `pacific`), read from the files the existing ML pipeline writes into
`<processed dir>/model/` (`oceanmind_model evaluate` and `export-dashboard` run with that dataset's config). Nothing is computed here but regional means.

Provenance is explicit: the ConvLSTM weights come from `checkpoint_origin.json` (for the Pacific dataset: trained on the NE Pacific study region and NOT retrained), and the
performance numbers are the ones measured on THIS dataset's held-out test split, compared with persistence and climatology."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services import environment_store as es
from app.services import geo_regions as geo
from app.services.environment import OutputsUnavailable

LEGACY = "ne_pacific"


def _dir(dataset: str) -> Path:
    ds = es.resolve_dataset_id(dataset)
    if ds == LEGACY:
        raise ValueError("The NE Pacific forecast is served by /api/monitor/*; this endpoint is for the other datasets")
    return es.dataset_refs()[ds].path / "model"


@lru_cache(maxsize=4)
def _read(path: str, stamp: float):
    d = Path(path)
    with np.load(d / "dashboard" / "snapshot.npz") as z:
        snap = {k: z[k] for k in z.files}
    info = json.loads((d / "dashboard" / "snapshot.json").read_text())
    metrics = json.loads((d / "model_metrics.json").read_text()) if (d / "model_metrics.json").exists() else None
    origin = json.loads((d / "checkpoint_origin.json").read_text()) if (d / "checkpoint_origin.json").exists() else None
    return snap, info, metrics, origin


def load(dataset: str):
    d = _dir(dataset)
    f = d / "dashboard" / "snapshot.npz"
    if not f.exists():
        raise OutputsUnavailable(f"No forecast exists for dataset {dataset!r}: run `python -m oceanmind_model evaluate` and `export-dashboard` with that dataset's config "
                                 "(it needs a checkpoint in <processed dir>/model/best_model.pt)")
    snap, info, metrics, origin = _read(str(d), f.stat().st_mtime)
    return snap, info, metrics, origin


def _weights(lat, mask):
    return np.cos(np.deg2rad(lat))[:, None] * mask


def _mean(a, w):
    ok = np.isfinite(a) & (w > 0)
    return None if not ok.any() else float((a[ok] * w[ok]).sum() / w[ok].sum())


def _region_mask(snap, region):
    reg = geo.get_region(region or "pacific")
    lat, lon = snap["lat"].astype("float64"), snap["lon"].astype("float64")
    m = geo.region_mask(reg, lat, lon)
    if not m.any():
        raise ValueError("The region does not overlap this dataset")
    return reg, lat, lon, m


def forecast(dataset: str, region: str | None = None) -> dict:
    snap, info, metrics, origin = load(dataset)
    reg, lat, lon, m = _region_mask(snap, region)
    w = _weights(lat, m)
    latest = info["latest"]
    fc, cl = snap["latest_forecast"], snap["latest_climatology"]
    n = fc.shape[0]
    f_sst = [_mean(fc[h], w) for h in range(n)]
    c_sst = [_mean(cl[h], w) for h in range(n)]
    last = _mean(snap["latest_obs"], w)
    last_clim = _mean(snap["latest_obs_climatology"], w)
    perf = None
    if metrics is not None:
        b = metrics["baselines"]
        perf = {"split": metrics["split"], "date_range": metrics["date_range"], "n_windows": metrics["n_windows"], "horizons": metrics["horizons"],
                "models": {k: {"mae": v["mae"], "rmse": v["rmse"], "r2": v["r2"], "mean_mae": v["mean_mae"], "mean_rmse": v["mean_rmse"]} for k, v in b.items()},
                "mae_skill_vs_persistence": b["convlstm"]["mae_skill_vs_persistence"], "beats_persistence": all(s > 0 for s in b["convlstm"]["mae_skill_vs_persistence"]),
                "evaluated_on": "this dataset's held-out test split, domain-wide (not per region)"}
    typical = perf["models"]["convlstm"]["mae"] if perf else None
    src = es.get_store(dataset).source
    out = {
        "dataset": dataset, "dataset_generated": src.get("is_observational") is False, "source": src, "region": {"id": reg.id, "name": reg.name}, "issued_from": latest["observed_date"], "target_dates": latest["target_dates"], "horizons": info["horizons"],
        "last_observed_sst": last, "last_observed_climatology": last_clim, "last_observed_anomaly": None if last is None or last_clim is None else last - last_clim,
        "forecast_sst": f_sst, "climatology_sst": c_sst, "persistence_sst": [last] * n,
        "forecast_anomaly": [None if f is None or c is None else f - c for f, c in zip(f_sst, c_sst)],
        "typical_error_c": typical,
        "model": {"name": info["model"], "checkpoint": info["checkpoint"], "origin": origin, "retrained_for_this_dataset": bool(origin and origin.get("retrained"))},
        "performance": perf,
        "note": info["latest"]["note"], "unit": "degC",
    }
    out["heatwave_continuation"] = _heatwave_continuation(dataset, reg.id, latest["observed_date"])
    from app.services import explain_service
    out["explanation"] = explain_service.explain_forecast(out)
    return out


def _heatwave_continuation(dataset: str, region_id: str, issued: str) -> dict:
    """Do the marine heatwaves that are active when the forecast is issued stay above the heatwave threshold on day 7? Area-weighted over the events in the region; only the
    events for which the model's forecast could be compared with the threshold count."""
    from app.services import heatwave_service as hws
    try:
        listing = hws.list_events(dataset, region=region_id if region_id != "pacific" else None)
    except Exception:  # noqa: BLE001 - heatwaves not built for this dataset
        return {"available": False, "message": "Marine-heatwave results are not available for this dataset, so no continuation can be assessed."}
    if listing["summary"]["latest_date"] != issued:
        return {"available": False, "message": f"The heatwave results are for {listing['summary']['latest_date']}, not for the date the forecast was issued from ({issued})."}
    ev = listing["items"]
    if not ev:
        return {"available": True, "events": 0, "message": "No marine heatwave is active in this region on the forecast's start date, so there is none to continue."}
    scored = [e for e in ev if e.get("forecast_still_above_p90_day7") is not None]
    if not scored:
        return {"available": False, "events": len(ev), "message": "The forecast could not be compared with the heatwave threshold for the active events."}
    w = [e["area_km2"] for e in scored]
    share = float(sum(e["forecast_still_above_p90_day7"] * a for e, a in zip(scored, w)) / sum(w))
    return {"available": True, "events": len(ev), "events_scored": len(scored), "area_km2": float(sum(e["area_km2"] for e in ev)), "share_still_above_day7": round(share, 3),
            "message": f"{len(ev)} marine heatwave(s) are active; the forecast keeps {share * 100:.0f}% of their area above the heatwave threshold on day 7 (model prediction)."}


def forecast_map(dataset: str, horizon: int, region: str | None = None, kind: str = "sst") -> dict:
    snap, info, metrics, origin = load(dataset)
    n = snap["latest_forecast"].shape[0]
    if not 1 <= horizon <= n:
        raise ValueError(f"horizon must be between 1 and {n}")
    if kind not in ("sst", "anomaly"):
        raise ValueError("kind must be sst or anomaly")
    reg, lat, lon, m = _region_mask(snap, region)
    a = snap["latest_forecast"][horizon - 1]
    if kind == "anomaly":
        a = a - snap["latest_climatology"][horizon - 1]
    rows = np.arange(np.flatnonzero(m.any(axis=1)).min(), np.flatnonzero(m.any(axis=1)).max() + 1)
    cols = np.flatnonzero(m.any(axis=0))
    cols = cols[np.argsort(geo.to_east(lon[cols]), kind="stable")]
    sel = np.ix_(rows, cols)
    v = np.where(m, a, np.nan)[sel]
    lo = lon[cols] if np.all(np.diff(lon[cols]) > 0) else geo.to_east(lon[cols])
    fin = v[np.isfinite(v)]
    h = float(info["grid"]["resolution_deg"]) / 2
    return {"dataset": dataset, "layer": "forecast" if kind == "sst" else "forecast_anomaly", "label": "Forecast SST" if kind == "sst" else "Forecast anomaly (forecast minus climatology)",
            "kind": "forecast", "unit": "degC", "horizon": horizon, "date": info["latest"]["target_dates"][horizon - 1], "issued_from": info["latest"]["observed_date"],
            "diverging": kind == "anomaly", "region": {"id": reg.id, "name": reg.name},
            "coverage": {"lat_min": float(lat.min() - h), "lat_max": float(lat.max() + h), "lon_min": float(lon.min() - h), "lon_max": float(lon.max() + h)},
            "lat": [round(float(x), 4) for x in lat[rows]], "lon": [round(float(x), 4) for x in lo],
            "values": [[None if not np.isfinite(x) else round(float(x), 2) for x in r] for r in v],
            "min": None if not fin.size else round(float(fin.min()), 2), "max": None if not fin.size else round(float(fin.max()), 2),
            "model": {"name": info["model"], "origin": origin}}
