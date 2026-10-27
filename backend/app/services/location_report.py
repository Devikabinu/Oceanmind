"""One report for one clicked place on the Ocean Map: conditions, anomaly (with explanation), marine-heatwave status, ecological risk (with drivers and explanation), species
nearby and their exposure, forecast and alerts. Everything is read from the existing stores (environment, heatwave results, risk inputs, forecast snapshot, species and alert tables)
for the SAME dataset, date and cell; nothing is computed that those services do not already produce, except neighbourhood and regional context statistics."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.biodiversity_observation import BiodiversityObservation
from app.models.species import Species
from app.repositories.alert_repository import dataset_filter
from app.services import climate_indices, dataset_alerts, explain_service, forecast_store, geo_regions as geo, risk_service
from app.services import environment_store as es
from app.services import heatwave_service as hws
from app.services.environment import OutputsUnavailable
from app.services import species_service
from app.services.taxonomy import CONSERVATION_SENSITIVE

SPECIES_RADIUS_DEG = 3.0
WINDOW_DAYS = risk_service.OVERLAP_WINDOW_DAYS
FACTOR_WORDS = {"anomaly": "SST anomaly", "persistence": "Marine heatwave persistence", "forecast": "Forecast conditions", "overlap": "Species / biodiversity evidence"}


def _lon180(lon: float) -> float:
    return ((lon + 180) % 360) - 180


def _km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def _heatwave(dataset: str, date: str, i: int, j: int, lat: float, lon_axis: float) -> dict:
    d = hws.state_for(dataset)
    if d is None or d.state is None:
        return {"available": False, "inside": None, "message": "Marine-heatwave results have not been built for this dataset."}
    if d.info["latest_date"] != date:
        return {"available": False, "inside": None, "latest_computed": d.info["latest_date"],
                "message": f"Marine-heatwave status is computed for the dataset's latest date ({d.info['latest_date']}), not for {date}."}
    inside = bool(d.state["active"][i, j])
    base = {"available": True, "inside": inside, "date": date, "baseline": d.info["baseline"], "threshold": d.info.get("threshold")}
    if not inside:
        return {**base, "message": "No active marine heatwave at this location."}
    idx = int(d.state["event_label"][i, j]) if "event_label" in d.state else 0
    event = d.info["events"][idx - 1] if 0 < idx <= len(d.info["events"]) else None
    if event is None:                                   # a heatwave cell in a cluster smaller than the event listing threshold
        return {**base, "run_days": int(d.state["run_len"][i, j]), "event": None, "current_anomaly_c": None,
                "message": "Marine heatwave: YES. This cell is in a heatwave state, in a cluster too small to be listed as an event."}
    return {**base, "run_days": int(d.state["run_len"][i, j]), "event_id": event["id"], "event_region": dataset_alerts.region_for(event["centroid"]["lat"], event["centroid"]["lon"])[1],
            "event": {k: event[k] for k in (
        "id", "start_date", "duration_days", "area_km2", "cells", "category", "category_name", "current_anomaly_c", "max_anomaly_c", "cumulative_intensity_c_days",
        "max_cumulative_intensity_c_days", "historical_percentile", "forecast_still_above_p90_day7", "bbox", "centroid") if k in event},
        "message": "Marine heatwave: YES.",
        "why_it_matters": ("Sustained warm anomalies are a recognised stressor for marine ecosystems, so large, long or intense events are given monitoring priority. "
                           "This system does not measure biological impact.")}


def _risk(db: Session, dataset: str, date: str, i: int, j: int, lat: float, lon180: float, cell: dict, provider: dict):
    inp = risk_service.inputs_for(dataset, date)
    overlap = risk_service.species_overlap_blocks(db, inp)
    g = risk_service.factor_grids(inp, overlap)
    a = risk_service.cell_assessment(inp, i, j, overlap, g)
    full = {**a, "dataset": dataset, "date": inp.date, "source": inp.source, "cell": {"lat": cell["lat"], "lon": cell["lon"], "lon_180": cell["lon_180"]}}
    expl = explain_service.explain_risk_cell(full)
    contrib = {c["factor"]: c for c in expl.get("contributions", [])}
    ev = a.get("evidence") or {}
    drivers = []
    for f in a["factors"]:
        k = f["factor"]
        row = {"factor": k, "label": FACTOR_WORDS[k], "weight": f["weight"], "available": f["available"]}
        if f["available"]:
            c = contrib.get(k, {})
            row.update(value=f["value"], level=f["level"], contribution=c.get("score_points"), weight_share=c.get("weight_share"), status="used in the score")
            row["explanation"] = {
                "anomaly": f"Anomaly of {ev.get('anomaly_c'):+.1f} °C gives a factor value of {f['value']:.2f} (|anomaly| / 3 °C, capped at 1)." if ev.get("anomaly_c") is not None else "",
                "persistence": f"The cell has been in a marine-heatwave run for {ev.get('heatwave_run_days')} days (days / 14, capped at 1).",
                "forecast": f"Mean forecast anomaly of {ev.get('forecast_mean_anomaly_c'):+.1f} °C over the next days (|anomaly| / 3 °C, capped at 1)." if ev.get("forecast_mean_anomaly_c") is not None else "",
                "overlap": f"{ev.get('n_species')} species have OBIS records in the surrounding 2°×2° block (n / 3, capped at 1).",
            }[k]
            if f.get("note"):
                row["explanation"] += f" Note: {f['note']}."
        else:
            row.update(value=None, level=None, contribution=None, weight_share=None, status="insufficient evidence",
                       explanation=(f.get("reason") or "no evidence for this cell").capitalize() + ". It is left out of the score and the other weights are rescaled; it is not counted as zero.")
        drivers.append(row)
    return {"status": a["status"], "score": a["score"], "level": a["level"], "evidence_completeness": a["evidence_completeness"], "drivers": drivers,
            "biodiversity_evidence": a["biodiversity_evidence"], "reasons": a["reasons"], "explanation": expl}, inp, g


def _species(db: Session, inp, hw, g, lat: float, lon180: float) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    box = {"lat_min": lat - SPECIES_RADIUS_DEG, "lat_max": lat + SPECIES_RADIUS_DEG, "lon_min": lon180 - SPECIES_RADIUS_DEG, "lon_max": lon180 + SPECIES_RADIUS_DEG}
    rows = db.execute(
        select(BiodiversityObservation.species_aphia_id, BiodiversityObservation.species_name, BiodiversityObservation.scientific_name, BiodiversityObservation.latitude,
               BiodiversityObservation.longitude, BiodiversityObservation.timestamp)
        .where(BiodiversityObservation.timestamp >= since, BiodiversityObservation.latitude.between(box["lat_min"], box["lat_max"]),
               BiodiversityObservation.longitude.between(box["lon_min"], box["lon_max"]))).all()
    cat = {s.aphia_id: s for s in db.execute(select(Species)).scalars()}
    by: dict = {}
    levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    for aid, name, sci, la, lo, ts in rows:
        key = aid or (name or sci)
        c = inp.cell(la, lo)
        e = by.setdefault(key, {"aphia_id": aid, "scientific_name": (cat[aid].scientific_name if aid in cat else (name or sci)), "n_records": 0, "nearest_km": 1e9, "latest": None,
                                "in_heatwave": 0, "anomalies": [], "risk": []})
        e["n_records"] += 1
        e["nearest_km"] = min(e["nearest_km"], _km(lat, lon180, la, lo))
        e["latest"] = max(filter(None, [e["latest"], ts.date().isoformat()]))
        if c is not None and np.isfinite(inp.anomaly[c]):
            e["anomalies"].append(float(inp.anomaly[c]))
            if hw and hw.get("state") is not None and hw["state"]["active"][c]:
                e["in_heatwave"] += 1
            sc = g["score"][c]
            if np.isfinite(sc):
                e["risk"].append(risk_service.level_for(float(sc)))
    out = []
    for e in sorted(by.values(), key=lambda e: (e["nearest_km"], -e["n_records"]))[:12]:
        s = cat.get(e["aphia_id"])
        worst = max(e["risk"], key=levels.index) if e["risk"] else None
        out.append({"aphia_id": e["aphia_id"], "scientific_name": e["scientific_name"], "common_name": s.common_name if s else None, "taxon_group": s.taxon_group if s else None,
                    "conservation_status": (s.iucn_category if s and s.iucn_category else "Status not confirmed"), "conservation_source": s.iucn_source if s and s.iucn_category else None,
                    "conservation_sensitive": bool(s and s.iucn_category in CONSERVATION_SENSITIVE), "n_records": e["n_records"], "nearest_km": round(e["nearest_km"]),
                    "latest_record": e["latest"], "records_in_heatwave": e["in_heatwave"] if hw and hw.get("state") is not None else None,
                    "mean_anomaly_c": round(float(np.mean(e["anomalies"])), 2) if e["anomalies"] else None, "highest_risk_level": worst,
                    "source": "OBIS"})
    n_exposed = sum(1 for s in out if s["records_in_heatwave"])
    n_high = sum(1 for s in out if s["highest_risk_level"] in ("HIGH", "CRITICAL"))
    note = ("No records were available in this dataset within about {r}° of this location. That is insufficient biodiversity coverage, not evidence that no species are present.".format(r=SPECIES_RADIUS_DEG)
            if not out else f"{len(out)} species with stored OBIS records within about {SPECIES_RADIUS_DEG}° ({n_exposed} with records inside a current marine heatwave, {n_high} with records in HIGH or CRITICAL risk cells). "
                            "Records are a sample: absence of records is not absence of species.")
    return {"radius_deg": SPECIES_RADIUS_DEG, "items": out, "summary": note, "evidence": "observed" if out else "insufficient_coverage"}


def _species_in_event(db: Session, inp, hwd, idx: int, top: int = 5) -> list[dict]:
    """Species with stored OBIS records in the cells that belong to one marine-heatwave event (its footprint, not its bounding box), most records first."""
    return species_in_mask(db, inp, hwd.state["event_label"] == idx, top)


def species_in_mask(db: Session, inp, mask: np.ndarray, top: int = 5) -> list[dict]:
    """Species with stored OBIS records in the cells of a boolean grid (on the dataset's grid), most records first."""
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    b = inp.bounds
    rows = db.execute(select(BiodiversityObservation.species_aphia_id, BiodiversityObservation.species_name, BiodiversityObservation.scientific_name,
                             BiodiversityObservation.latitude, BiodiversityObservation.longitude)
                      .where(BiodiversityObservation.timestamp >= since, BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]),
                             risk_service._lon_clause(b, inp.lon_origin))).all()
    count: dict = {}
    for aid, name, sci, la, lo in rows:
        c = inp.cell(la, lo)
        if c is None or not mask[c]:
            continue
        k = aid or name or sci
        count[k] = count.get(k, 0) + 1
    cat = {s.aphia_id: s for s in db.execute(select(Species)).scalars()}
    out = []
    for k, n in sorted(count.items(), key=lambda kv: -kv[1])[:top]:
        s = cat.get(k) if isinstance(k, int) else None
        out.append({"aphia_id": k if isinstance(k, int) else None, "scientific_name": s.scientific_name if s else str(k), "common_name": s.common_name if s else None,
                    "iucn_category": s.iucn_category if s else None, "n_records": n})
    return out


def species_in_event_footprint(db: Session, dataset: str, event_id: str, top: int = 8) -> list[dict] | None:
    """Species with stored records in the cells of an ACTIVE marine-heatwave event of a dataset (its footprint on the latest date). None when the event or its footprint is not
    available, so callers can fall back to a coarser statement instead of guessing."""
    hwd = hws.state_for(dataset)
    if hwd is None or hwd.state is None or "event_label" not in hwd.state:
        return None
    idx = next((k for k, e in enumerate(hwd.info["events"], 1) if e["id"] == event_id), None)
    if idx is None:
        return None
    inp = risk_service.inputs_for(dataset, hwd.info["latest_date"])
    return _species_in_event(db, inp, hwd, idx, top)


def _event_relations(db: Session, hw: dict, hwd, g: dict, inp=None) -> None:
    """Species and ecological-risk relationship of the whole event the clicked cell belongs to (from stored records and the risk surface)."""
    ev = hw["event"]
    idx = next(k for k, e in enumerate(hwd.info["events"], 1) if e["id"] == ev["id"])
    sc = g["score"][hwd.state["event_label"] == idx]
    sc = sc[np.isfinite(sc)]
    levels = [risk_service.level_for(float(x)) for x in sc]
    ev["risk_in_event"] = {"cells_assessed": int(sc.size), "mean_score": round(float(sc.mean()), 2) if sc.size else None,
                           "share_high_or_critical": round(sum(1 for lv in levels if lv in ("HIGH", "CRITICAL")) / len(levels), 3) if levels else None}
    sp = _species_in_event(db, inp, hwd, idx) if inp is not None else []
    ev["affected_species"] = [{"scientific_name": s["scientific_name"], "common_name": s["common_name"], "n_records": s["n_records"],
                               "conservation_status": s.get("iucn_category") or "Status not confirmed"} for s in sp]
    r = ev["risk_in_event"]
    ev["ecological_relationship"] = (
        (f"{r['share_high_or_critical'] * 100:.0f}% of the event's {r['cells_assessed']} assessed cells are rated HIGH or CRITICAL ecological risk (mean score {r['mean_score']:.2f}). " if r["mean_score"] is not None else "")
        + (f"OBIS records of {len(sp)} species lie in cells that are part of this event." if sp else "No OBIS records lie in the cells of this event (insufficient biodiversity coverage, not evidence of absence)."))


def _forecast(dataset: str, i: int, j: int, sst: float | None, anom_now: float | None = None, hw: dict | None = None, risk: dict | None = None) -> dict:
    if dataset == "ne_pacific":
        return {"available": False, "message": "The NE Pacific forecast is shown on the NE Pacific forecast page."}
    try:
        snap, info, metrics, origin = forecast_store.load(dataset)
    except OutputsUnavailable as exc:
        return {"available": False, "message": str(exc)}
    fc, cl = snap["latest_forecast"][:, i, j], snap["latest_climatology"][:, i, j]
    if not np.isfinite(fc).all():
        return {"available": False, "message": "No forecast value for this cell."}
    anom = fc - cl
    slope = float(np.polyfit(np.arange(len(fc)), fc, 1)[0])
    direction = "warming" if slope > 0.02 else "cooling" if slope < -0.02 else "stable"
    err = metrics["baselines"]["convlstm"]["mae"] if metrics else None
    beats = bool(metrics and all(x > 0 for x in metrics["baselines"]["convlstm"]["mae_skill_vs_persistence"]))
    return {"available": True, "issued_from": info["latest"]["observed_date"], "dates": info["latest"]["target_dates"], "forecast_sst": [round(float(x), 2) for x in fc],
            "climatology": [round(float(x), 2) for x in cl], "forecast_anomaly": [round(float(x), 2) for x in anom], "current_sst": sst, "persistence_sst": [sst] * len(fc) if sst is not None else None, "change_c": round(float(fc[-1] - (sst if sst is not None else fc[0])), 2),
            "direction": direction, "typical_error_c": None if err is None else [round(float(x), 2) for x in err],
            "model": info["model"], "trained_on": origin["trained_on"] if origin else None, "beats_persistence": beats if metrics else None,
            "interpretation": _forecast_reading(direction, anom_now, anom, fc, hw, risk, err),
            "summary": (f"The model expects {direction} over the next {len(fc)} days: {fc[-1]:.1f} °C on {info['latest']['target_dates'][-1]} ({anom[-1]:+.1f} °C versus normal)"
                        + (f", typical error ±{err[-1]:.2f} °C at day {len(fc)}." if err else ". Its error on this dataset has not been measured."))}


def _forecast_reading(direction: str, anom_now, anom, fc, hw, risk, err) -> list[str]:
    """What the forecast means for this place, phrased as an expectation with its measured uncertainty (never as certainty)."""
    n = len(fc)
    out = [f"Expected direction: {direction} ({fc[0]:.1f} to {fc[-1]:.1f} °C over {n} days). This is a model prediction, not an observation."]
    if anom_now is not None:
        if abs(anom_now) >= 0.5:
            keeps = (anom[-1] > 0) == (anom_now > 0) and abs(anom[-1]) >= 0.5
            out.append(f"The current anomaly ({anom_now:+.1f} °C) is expected to {'persist' if keeps else 'ease'}: the day-{n} forecast anomaly is {anom[-1]:+.1f} °C.")
        else:
            out.append(f"The current anomaly is small ({anom_now:+.1f} °C); the forecast anomaly on day {n} is {anom[-1]:+.1f} °C.")
    if hw and hw.get("inside"):
        p = (hw.get("event") or {}).get("forecast_still_above_p90_day7")
        if p is None:
            out.append("The model does not provide a heatwave-continuation estimate for this event.")
        elif p >= 0.5:
            out.append(f"Heatwave conditions here may continue: the model keeps {p * 100:.0f}% of the event's area above the threshold on day {n}.")
        else:
            out.append(f"Heatwave conditions may ease: the model keeps only {p * 100:.0f}% of the event's area above the threshold on day {n}.")
    if risk and risk.get("drivers"):
        d = {x["factor"]: x for x in risk["drivers"]}
        v = d.get("anomaly", {}).get("value")
        if v is not None and abs(anom[-1]) / 3 < v - 0.05:
            out.append("The anomaly driver of ecological risk would decrease if this forecast verifies.")
        elif v is not None and abs(anom[-1]) / 3 > v + 0.05:
            out.append("The anomaly driver of ecological risk would increase if this forecast verifies.")
    if err:
        out.append(f"Typical model error is ±{err[0]:.2f} °C at day 1, rising to ±{err[-1]:.2f} °C at day {n}; smaller changes than that are not meaningful.")
    return out


def _alerts(db: Session, dataset: str, lat: float, lon180: float, hw: dict, region_ids: list[str]) -> list[dict]:
    rows = db.execute(select(Alert).where(dataset_filter(dataset)).order_by(Alert.timestamp.desc()).limit(400)).scalars().all()
    out = []
    ev_id = hw.get("event_id")
    for a in rows:
        d = a.details or {}
        near = _km(lat, lon180, a.latitude, a.longitude) <= 800
        same_event = bool(ev_id and d.get("event_id") == ev_id)
        if same_event or near:
            out.append({"id": str(a.id), "alert_type": a.alert_type, "severity": a.severity.value, "message": a.message, "timestamp": a.timestamp.isoformat(), "status": a.status.value,
                        "region": d.get("region"), "latitude": a.latitude, "longitude": a.longitude, "reasons": d.get("reasons", [])[:4], "evidence_summary": d.get("evidence_summary", []),
                        "same_event": same_event, "distance_km": round(_km(lat, lon180, a.latitude, a.longitude))})
    return sorted(out, key=lambda a: (not a["same_event"], a["distance_km"]))[:6]


def report(db: Session, dataset: str | None, lat: float, lon: float, date) -> dict:
    pt = es.point_response(dataset, lat, lon, date)
    ds = pt["dataset"]["id"]
    out: dict = {"dataset": ds, "date": pt["date"], "latest_available_date": pt["latest_available_date"], "query": {"lat": lat, "lon": lon}, "status": pt["status"], "cell": pt["cell"],
                 "message": pt["message"], "provider": pt["provider"], "kind": pt["kind"], "unit": "degC"}
    if pt["status"] != "valid":
        return out
    c = pt["cell"]
    i, j = c["row"], c["col"]
    store = es.get_store(ds)
    lon180 = c["lon_180"]
    region_id, region_name = dataset_alerts.region_for(c["lat"], c["lon"])
    sst, anom = pt["sst"], pt["anomaly"]
    normal = None if anom is None else round(sst - anom, 2)
    out["region"] = {"id": region_id, "name": region_name, "contains": dataset_alerts.regions_containing(c["lat"], c["lon"])}
    out["conditions"] = {"sst": sst, "normal_sst": normal, "anomaly": anom, "unit": "degC"}

    hw = _heatwave(ds, pt["date"], i, j, c["lat"], c["lon"])
    out["heatwave"] = hw

    # context statistics for the anomaly explanation
    pctl = nb_mean = None
    nb_n = 0
    try:
        vals, status, _ = store.native_layer("anomaly", pt["date"])
        reg = geo.get_region(region_id)
        m = geo.region_mask(reg, store.lat, store.lon) & np.isfinite(vals)
        if anom is not None and m.any():
            pctl = round(100.0 * float((vals[m] < anom).mean()), 1)
        win = vals[max(0, i - 2): i + 3, max(0, j - 2): j + 3]
        win = win[np.isfinite(win)]
        nb_n, nb_mean = int(win.size), (float(win.mean()) if win.size else None)
    except Exception:  # context is optional; the explanation then simply omits it
        pass
    hwd0 = hws.state_for(ds)
    h_pct, h_n = (store.historical_anomaly(i, j, store.resolve_date(pt["date"]), anom) if anom is not None else (None, 0))
    out["anomaly"] = {"historical_percentile": h_pct, "historical_samples": h_n, "value": anom, "class": explain_service.anomaly_class(anom), "region_percentile": pctl, "neighbourhood_mean": None if nb_mean is None else round(nb_mean, 2),
                      "explanation": explain_service.explain_anomaly({"date": pt["date"], "sst": sst, "normal": normal, "anomaly": anom, "region_name": region_name, "region_percentile": pctl,
                                                                       "neighbourhood_mean": nb_mean, "neighbourhood_cells": nb_n, "heatwave": hw, "history": {"percentile": h_pct, "n": h_n}, "baseline": hwd0.info["baseline"] if hwd0 else None,
                                                                       "lat": c["lat"], "lon_180": lon180, "climate": climate_indices.context(pt["date"])})}
    try:
        risk, inp, g = _risk(db, ds, pt["date"], i, j, c["lat"], c["lon"], c, pt["provider"])
        out["risk"] = risk
        hwd = hws.state_for(ds)
        out["species"] = _species(db, inp, {"state": hwd.state} if hwd and hwd.info["latest_date"] == pt["date"] else None, g, c["lat"], lon180)
        if hw.get("inside") and hw.get("event") and hwd is not None and hwd.state is not None and "event_label" in hwd.state:
            _event_relations(db, hw, hwd, g, inp)
    except (OutputsUnavailable, ValueError) as exc:
        out["risk"] = {"status": "unavailable", "message": str(exc)}
        out["species"] = {"items": [], "summary": "Species context unavailable for this dataset.", "evidence": "unavailable", "radius_deg": SPECIES_RADIUS_DEG}
    out["forecast"] = _forecast(ds, i, j, sst, anom, hw, out.get("risk"))
    out["alerts"] = _alerts(db, ds, c["lat"], lon180, hw, out["region"]["contains"])
    return out


def species_layer(db: Session, dataset: str | None, region: str | None, date) -> dict:
    """Species records inside the dataset domain as map points (per species and 0.5° cell), with conservation status and exposure to the current heatwave and risk."""
    inp = risk_service.inputs_for(dataset or "pacific", date)
    reg = geo.get_region(region or "pacific")
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    b = inp.bounds
    rows = db.execute(
        select(BiodiversityObservation.species_aphia_id, BiodiversityObservation.species_name, BiodiversityObservation.scientific_name, BiodiversityObservation.latitude,
               BiodiversityObservation.longitude, BiodiversityObservation.timestamp)
        .where(BiodiversityObservation.timestamp >= since, BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]), risk_service._lon_clause(b, inp.lon_origin))).all()
    cat = {s.aphia_id: s for s in db.execute(select(Species)).scalars()}
    hw = hws.state_for(inp.dataset)
    hw_on = bool(hw and hw.state is not None and hw.info["latest_date"] == inp.date)
    overlap = risk_service.species_overlap_blocks(db, inp)
    g = risk_service.factor_grids(inp, overlap)
    alert_by_species: dict = {}
    for a in db.execute(select(Alert).where(dataset_filter(inp.dataset))).scalars():
        for s in (a.details or {}).get("species", []) or []:
            if s.get("aphia_id") and (a.details or {}).get("driver") == "Species exposure":
                alert_by_species[s["aphia_id"]] = a.severity.value
    pts: dict = {}
    for aid, name, sci, la, lo, ts in rows:
        c = inp.cell(la, lo)
        if c is None or not np.isfinite(inp.anomaly[c]):
            continue
        if not bool(geo.region_mask(reg, [la], [lo])[0, 0]):
            continue
        key = (aid or name or sci, round(la * 2) / 2, round(float(lo) * 2) / 2)
        e = pts.get(key)
        if e is None:
            s = cat.get(aid)
            sc = g["score"][c]
            e = pts[key] = {"aphia_id": aid, "scientific_name": s.scientific_name if s else (name or sci), "common_name": s.common_name if s else None,
                            "taxon_group": s.taxon_group if s else None, "conservation_status": (s.iucn_category if s and s.iucn_category else "Status not confirmed"),
                            "conservation_source": s.iucn_source if s and s.iucn_category else None, "lat": float(la), "lon_180": float(lo),
                            "lon": float(inp.axis_lon(lo)), "n_records": 0, "latest": None, "anomaly_c": round(float(inp.anomaly[c]), 2),
                            "alert_severity": alert_by_species.get(aid), "in_heatwave": bool(hw_on and hw.state["active"][c]), "risk_level": risk_service.level_for(float(sc)) if np.isfinite(sc) else None, "source": "OBIS (stored sample)"}
        e["n_records"] += 1
        e["latest"] = max(filter(None, [e["latest"], ts.date().isoformat()]))
    # threatened and near-threatened species come first, so the cap on the number of points never drops a CR/EN/VU/NT record in favour of a well-recorded species
    items = sorted(pts.values(), key=lambda e: (e["conservation_status"] not in ("CR", "EN", "VU", "NT"), -e["n_records"]))[:2500]
    return {"dataset": inp.dataset, "date": inp.date, "region": {"id": reg.id, "name": reg.name}, "items": items, "heatwave_computed": hw_on,
            "summary": {"points": len(items), "species": len({e["scientific_name"] for e in items}), "records": sum(e["n_records"] for e in items),
                        "points_in_heatwave": sum(1 for e in items if e["in_heatwave"]), "points_high_risk": sum(1 for e in items if e["risk_level"] in ("HIGH", "CRITICAL")),
                        "conservation_sensitive_species": len({e["scientific_name"] for e in items if e["conservation_status"] in CONSERVATION_SENSITIVE}),
                        "threatened_in_heatwave": len({e["scientific_name"] for e in items if e["in_heatwave"] and e["conservation_status"] in ("CR", "EN", "VU", "NT")}),
                        "with_alert": len({e["scientific_name"] for e in items if e["alert_severity"]})},
            "note": "Observed record density from stored OBIS records, not a species range. Absence of a marker is not absence of the species."}


def species_exposure(db: Session, dataset: str | None, aphia_id: int, date) -> dict:
    """Exposure of ONE species' stored records to the day's anomaly, marine heatwaves and ecological risk, with a plain-language explanation."""
    sp = db.execute(select(Species).where(Species.aphia_id == aphia_id)).scalar_one_or_none()
    if sp is None:
        raise ValueError(f"unknown species {aphia_id}")
    inp = risk_service.inputs_for(dataset or "pacific", date)
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    b = inp.bounds
    rows = db.execute(select(BiodiversityObservation.latitude, BiodiversityObservation.longitude, BiodiversityObservation.timestamp).where(
        (BiodiversityObservation.species_aphia_id == aphia_id) | (BiodiversityObservation.scientific_name == sp.scientific_name), BiodiversityObservation.timestamp >= since,
        BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]), risk_service._lon_clause(b, inp.lon_origin))).all()
    hw = hws.state_for(inp.dataset)
    hw_on = bool(hw and hw.state is not None and hw.info["latest_date"] == inp.date)
    g = risk_service.factor_grids(inp, risk_service.species_overlap_blocks(db, inp))
    cells, an, inhw, rl, regions, lats, latest = set(), [], 0, [], {}, [], None
    levels = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    for la, lo, ts in rows:
        c = inp.cell(la, lo)
        if c is None or not np.isfinite(inp.anomaly[c]):
            continue
        cells.add(c)
        an.append(float(inp.anomaly[c]))
        lats.append(la)
        latest = max(filter(None, [latest, ts.date().isoformat()]))
        inhw += int(bool(hw_on and hw.state["active"][c]))
        sc = g["score"][c]
        if np.isfinite(sc):
            rl.append(risk_service.level_for(float(sc)))
        nm = dataset_alerts.region_for(la, float(inp.axis_lon(lo)))[1]
        regions[nm] = regions.get(nm, 0) + 1
    fc_mean = None
    try:
        fsnap, finfo, _m, _o = forecast_store.load(inp.dataset)
        if finfo["latest"]["observed_date"] == inp.date:
            fa = np.nanmean(fsnap["latest_forecast"] - fsnap["latest_climatology"], axis=0)
            vals = [float(fa[c]) for c in cells if np.isfinite(fa[c])]
            fc_mean = float(np.mean(vals)) if vals else None
    except (OutputsUnavailable, ValueError):
        pass
    alert_sev = None
    for a in db.execute(select(Alert).where(dataset_filter(inp.dataset))).scalars():
        d = a.details or {}
        if d.get("driver") == "Species exposure" and any(s.get("aphia_id") == aphia_id for s in d.get("species", []) or []):
            alert_sev = a.severity.value
    base = {"aphia_id": aphia_id, "scientific_name": sp.scientific_name, "common_name": sp.common_name, "taxon_group": sp.taxon_group, "dataset": inp.dataset, "date": inp.date,
            "conservation_status": sp.iucn_category or "Status not confirmed", "conservation_source": sp.iucn_source if sp.iucn_category else None,
            "conservation_sensitive": sp.iucn_category in CONSERVATION_SENSITIVE, "source": "OBIS (stored sample)"}
    if not an:
        return {**base, "available": False, "message": "No stored records inside this dataset in the last two years: insufficient evidence to assess exposure (not evidence that the species is absent)."}
    n = len(an)
    x = {**base, "available": True, "n_records": n, "n_cells": len(cells), "latest_record": latest, "latitude_range": [min(lats), max(lats)], "mean_anomaly_c": float(np.mean(an)),
         "max_anomaly_c": float(max(an, key=abs)), "share_anomaly_1c": sum(1 for v in an if abs(v) >= 1.0) / n, "heatwave_available": hw_on,
         "share_in_heatwave": inhw / n if hw_on else None, "share_high_risk": (sum(1 for v in rl if v in ("HIGH", "CRITICAL")) / len(rl)) if rl else None,
         "highest_risk_level": max(rl, key=levels.index) if rl else None, "top_region": max(regions, key=regions.get) if regions else None,
         "mean_forecast_anomaly_c": fc_mean, "alert_severity": alert_sev}
    x["explanation"] = explain_service.explain_species({**x, "share_in_heatwave": x["share_in_heatwave"] or 0.0})
    return x
