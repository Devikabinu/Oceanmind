"""The physical explanation of one place: the existing SST observation, anomaly, recent evolution and ConvLSTM forecast, matched to the measured physical drivers and assessed by
physical_analysis. It reads the same processed dataset as the location report (so the dates agree) and never changes the forecast, the risk score or the model."""
from __future__ import annotations

import math
from datetime import date as _date, timedelta

import numpy as np

from app.services import dataset_alerts
from app.services import environment_store as es
from app.services import forecast_reading as fr
from app.services import location_report as lr
from app.services import physical_analysis as pa
from app.services import physical_drivers as pdv
from app.services import physical_interpretation as pi
from app.services import report_analysis as ra

GRADIENT_CELLS = 2             # the SST gradient is taken over +-2 grid cells (0.5 degrees) to damp grid-scale noise
COAST_CELLS = 6                # land within +-6 cells (1.5 degrees) makes a place coastal


def sst_gradient(store, date: str, i: int, j: int) -> dict | None:
    """-> {dTdx, dTdy in degC per metre (east, north), date}, from the latest SST field; None when a neighbouring value is missing."""
    sst, _, t = store.native_layer("sst", date)
    k = GRADIENT_CELLS
    if i - k < 0 or j - k < 0 or i + k >= sst.shape[0] or j + k >= sst.shape[1]:
        return None
    vals = [sst[i, j + k], sst[i, j - k], sst[i + k, j], sst[i - k, j]]
    if not all(np.isfinite(v) for v in vals):
        return None
    dy = 2 * k * store.res * 111.32e3
    dx = 2 * k * store.res * 111.32e3 * max(math.cos(math.radians(float(store.lat[i]))), 0.05)
    return {"dTdx_c_per_m": float((sst[i, j + k] - sst[i, j - k]) / dx), "dTdy_c_per_m": float((sst[i + k, j] - sst[i - k, j]) / dy), "date": str(t.date())}


def coast_geometry(store, i: int, j: int) -> dict:
    """Whether land lies within 1.5 degrees and the direction away from it (east, north), estimated from the land mask. Approximate: the mask is 0.25 degrees."""
    k = COAST_CELLS
    i0, i1, j0, j1 = max(0, i - k), min(store.land.shape[0], i + k + 1), max(0, j - k), min(store.land.shape[1], j + k + 1)
    L = store.land[i0:i1, j0:j1].astype(float)
    if L.sum() < 4:
        return {"near_coast": False}
    ys, xs = np.mgrid[i0:i1, j0:j1]
    vx = float(((xs - xs.mean()) * L).sum() / ((xs - xs.mean()) ** 2).sum())
    vy = float(((ys - ys.mean()) * L).sum() / ((ys - ys.mean()) ** 2).sum())
    n = math.hypot(vx, vy)
    if n < 1e-9:
        return {"near_coast": False}
    return {"near_coast": True, "offshore": (-vx / n, -vy / n), "land_fraction": float(L.mean())}


def build_report(dataset: str | None, lat: float, lon: float, wait_s: float = 6.0) -> dict:
    pt = es.point_response(dataset, lat, lon, None)
    if pt["status"] != "valid":
        return {"available": False, "status": pt["status"], "message": pt["message"] or "There is no sea surface temperature at this place, so there is no anomaly to explain."}
    c = pt["cell"]
    i, j = c["row"], c["col"]
    ds = pt["dataset"]["id"]
    store = es.get_store(ds)
    date, sst, anom = pt["date"], pt["sst"], pt["anomaly"]
    if anom is None:
        return {"available": False, "status": "no_anomaly", "message": "No SST anomaly exists for this place and date, so no physical explanation is attempted."}
    out = {"conditions": {"sst": sst, "anomaly": anom, "normal_sst": round(sst - anom, 2)}, "forecast": lr._forecast(ds, i, j, sst, anom, None, None, date), "heatwave": {}, "species": {}, "risk": None}
    ra.build(out, store, date, i, j)                                             # the same forecast reading and recent-trend code as the location report
    recent = ra.recent_series(store, date, i, j, n=14)
    tr = ra.trends(recent[-7:])
    f = out["forecast"] if out["forecast"].get("available") else None
    drivers = pdv.location_drivers(c["lat"], c["lon_180"], wait_s, _date.fromisoformat(date) + timedelta(days=1))         # the seasonal heat-flux window starts with the forecast week
    if drivers is None:
        return {"available": False, "status": "disabled", "message": "Physical-driver retrieval is switched off."}
    if drivers["status"] in ("refreshing", "unavailable") and not any(drivers.get(k) for k in ("winds", "sea_level", "currents", "enso", "heat_flux")):
        return {"available": False, "status": drivers["status"], "refresh_hint_s": 12 if drivers["status"] == "refreshing" else None,
                "message": "Retrieving the measured winds, sea level, currents and climate indices for this place." if drivers["status"] == "refreshing" else "The external environmental datasets could not be reached just now; the SST and forecast explanation above are unaffected."}
    window_sst = None
    rw = (drivers.get("radiation") or {}).get("window")
    if rw:                                                                       # SST and its normal over the days of the radiation window, for the heat-flux estimate
        try:
            span = (_date.fromisoformat(date) - _date.fromisoformat(rw["start"])).days + 1
            rows = [r for r in ra.recent_series(store, date, i, j, n=max(span, 7)) if rw["start"] <= r["date"] <= rw["end"]] if 0 < span <= 60 else []
            if len(rows) >= 5:
                window_sst = {"sst": float(np.mean([r["sst_c"] for r in rows])), "normal": float(np.mean([r["sst_c"] - r["anomaly_c"] for r in rows])), "start": rows[0]["date"], "end": rows[-1]["date"], "days": len(rows)}
        except (ValueError, KeyError):
            window_sst = None
    ctx = {"window_sst": window_sst, "date": date, "lat": c["lat"], "lon": c["lon_180"], "sst": sst, "anomaly": anom, "recent": recent, "trends": tr, "reading": out["forecast"].get("reading"), "forecast": f, "advection": sst_gradient(store, date, i, j),
           "coast": coast_geometry(store, i, j), "baseline": f"{store.train_period[0][:4]}-{store.train_period[1][:4]} climatological baseline" if getattr(store, "train_period", None) else None}
    ctx["heatwave"] = lr._heatwave(ds, date, i, j, c["lat"], c["lon"])
    analysis = pa.analyse(drivers, ctx)
    pkg = pi.build_package(analysis, ctx, dataset_alerts.region_for(c["lat"], c["lon_180"])[1])
    interp = pi.interpret(pkg)
    generating = interp["provider"]["status"] == "generating"
    hint = 12 if drivers["status"] == "stale_cache" else 8 if generating else None
    return {"available": True, "status": drivers["status"], "cell": {"lat": c["lat"], "lon": c["lon_180"]}, "refresh_hint_s": hint, **analysis, "interpretation": interp, "evidence_package": pkg}
