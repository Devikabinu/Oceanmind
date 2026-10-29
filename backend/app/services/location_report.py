"""One report for one clicked place on the Ocean Map: conditions, anomaly (with explanation), marine-heatwave status, ecological risk (with drivers and explanation), species
nearby and their exposure, forecast and alerts. Everything is read from the existing stores (environment, heatwave results, risk inputs, forecast snapshot, species and alert tables)
for the SAME dataset, date and cell; nothing is computed that those services do not already produce, except neighbourhood and regional context statistics."""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.biodiversity_observation import BiodiversityObservation
from app.models.species import Species
from app.repositories.alert_repository import dataset_filter
from app.services import climate_indices, dataset_alerts, explain_service, forecast_store, geo_regions as geo, risk_service
from app.services import environment_store as es
from app.services import heatwave_service as hws
from app.services.environment import OutputsUnavailable
from app.services import biodiversity_view, obis_service, ocean_context
from app.services import forecast_reading as fr
from app.services import report_analysis, species_service
from app.services.taxonomy import CONSERVATION_SENSITIVE

SPECIES_RADIUS_DEG = 3.0
WIDE_RADIUS_DEG = 20.0                   # last resort for very sparse areas, older records included, always labelled regional and historical
REGIONAL_RADIUS_DEG = 10.0               # sparse areas: the records of this wider neighbourhood are used, and labelled as regional
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


def block_records(db: Session, inp, i: int, j: int) -> dict:
    """What the species factor of cell (i, j) is made from: the OBIS observations in its 2x2 degree block within the last WINDOW_DAYS days. Counts what is counted:
    `observations` = stored records, `species` = distinct species among them, `latest` = date of the newest record."""
    B = inp.block
    r0, r1, c0, c1 = (i // B) * B, (i // B + 1) * B, (j // B) * B, (j // B + 1) * B
    lat_lo, lat_hi = float(inp.lat[r0:r1].min()) - inp.res / 2, float(inp.lat[r0:r1].max()) + inp.res / 2
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    rows = db.execute(select(func.coalesce(BiodiversityObservation.species_name, BiodiversityObservation.scientific_name), BiodiversityObservation.latitude,
                             BiodiversityObservation.longitude, BiodiversityObservation.timestamp)
                      .where(BiodiversityObservation.timestamp >= since, BiodiversityObservation.latitude.between(lat_lo, lat_hi))).all()
    n, names, latest = 0, set(), None
    for name, la, lo, ts in rows:
        c = inp.cell(la, lo)
        if c is None or not (r0 <= c[0] < r1 and c0 <= c[1] < c1):
            continue
        n += 1
        names.add(name)
        latest = ts if latest is None or ts > latest else latest
    return {"observations": n, "species": len(names), "latest": None if latest is None else latest.date().isoformat(), "window_days": WINDOW_DAYS,
            "block": {"lat_min": round(lat_lo, 2), "lat_max": round(lat_hi, 2)}}


def _driver_text(k: str, f: dict, ev: dict, bio: dict | None) -> str:
    sat = f["saturation_at"]
    why = {"anomaly": "the observed anomaly", "persistence": "the heatwave duration", "forecast": "the forecast anomaly", "overlap": "the number of species"}[k]
    cap = f" Saturated because {why} exceeds the scoring threshold ({sat:g} {f['raw_unit']}); the factor stops increasing there, which does not mean the physical value is 100%." if f.get("saturated") else ""
    if k == "anomaly":
        return f"|anomaly| {abs(ev['anomaly_c']):.2f} °C / {sat:g} °C = {f['ratio']:.2f}, factor {f['value']:.2f}.{cap}" if ev.get("anomaly_c") is not None else ""
    if k == "persistence":
        return f"The cell has been in a marine-heatwave run for {ev.get('heatwave_run_days')} days; days / {sat:g} = {f['ratio']:.2f}, factor {f['value']:.2f}. 0 days means evidence is present and the cell is not in a heatwave.{cap}"
    if k == "forecast":
        part = f" Only {f['days_with_data']} of the forecast days have a value here." if f["status"] == "incomplete" else ""
        return (f"Mean size of the forecast anomaly over {ev.get('forecast_days')} days is {ev.get('forecast_mean_abs_anomaly_c'):.2f} °C (signed mean {ev.get('forecast_mean_anomaly_c'):+.2f} °C); "
                f"/ {sat:g} °C = {f['ratio']:.2f}, factor {f['value']:.2f}.{part}{cap}")
    if f.get("scope") == "nearby":
        return (f"{ev.get('n_species')} distinct species have OBIS records in the nearest sampled 2°×2° block, about {f['distance_deg']:g}° away (nearby records, not records at this cell); "
                f"species / {sat:g} = {f['ratio']:.2f}, factor {f['value']:.2f}.{cap}")
    obs = f" ({bio["observations"]} stored observation(s) in the block, newest {bio['latest']})" if bio and bio["observations"] else ""
    return f"{ev.get('n_species')} species (distinct) have OBIS records in this 2°×2° block in the last {WINDOW_DAYS} days{obs}; species / {sat:g} = {f['ratio']:.2f}, factor {f['value']:.2f}.{cap}"


def _risk(db: Session, dataset: str, date: str, i: int, j: int, lat: float, lon180: float, cell: dict, provider: dict):
    inp = risk_service.inputs_for(dataset, date)
    overlap = risk_service.species_overlap_blocks(db, inp)
    g = risk_service.factor_grids(inp, overlap)
    a = risk_service.cell_assessment(inp, i, j, overlap, g)
    full = {**a, "dataset": dataset, "date": inp.date, "source": inp.source, "cell": {"lat": cell["lat"], "lon": cell["lon"], "lon_180": cell["lon_180"]}}
    expl = explain_service.explain_risk_cell(full)
    ev = a.get("evidence") or {}
    bio = block_records(db, inp, i, j) if overlap is not None else None
    drivers = []
    for f in a["factors"]:
        k = f["factor"]
        row = {"factor": k, "label": FACTOR_WORDS[k], "weight": f["nominal_weight"], "effective_weight": f["effective_weight"], "available": f["available"], "status": f["status"],
               "raw": f["raw"], "raw_unit": f["raw_unit"], "saturation_at": f["saturation_at"], "saturated": f["saturated"], "ratio": f["ratio"],
               "normalization": f.get("normalization"), "scope": f.get("scope", "local" if k == "overlap" else None), "distance_deg": f.get("distance_deg")}
        if f["available"]:
            row.update(value=f["value"], value_exact=f["value_exact"], level=f["level"], contribution=f["contribution"], weight_share=f["effective_weight"],
                       status_text={"contributing": "Evidence present and contributing to the score", "below_threshold": "Evidence present; small, so it adds little to the score (not 'insufficient')",
                                    "incomplete": "Evidence present but incomplete; used as far as it goes"}[f["status"]])
            row["explanation"] = _driver_text(k, f, ev, bio) + (f" Note: {f['note']}." if f.get("note") else "")
            if k == "overlap" and bio:
                row["evidence_detail"] = bio
        else:
            row.update(value=None, level=None, contribution=None, weight_share=None, missing_input=f["missing_input"], status_text="No input was found for this area, even after widening the search; the score is renormalised over the available indicators",
                       explanation=f"No stored data were found for this indicator within the search range. The score is computed from the other indicators (weights renormalised); it is not treated as zero.")
            if k == "overlap" and bio is not None:
                row["evidence_detail"] = bio
        drivers.append(row)
    br = a["score_breakdown"]
    terms = " + ".join(f"{t['contribution']:.2f}" for t in br["terms"])
    return {"status": a["status"], "score": a["score"], "level": a["level"], "evidence_completeness": a["evidence_completeness"], "drivers": drivers,
            "score_breakdown": {**br, "text": f"{terms} = {br['sum']:.2f}" if br["terms"] else None},
            "biodiversity_evidence": a["biodiversity_evidence"], "reasons": a["reasons"], "explanation": expl}, inp, g


def _species(db: Session, inp, hw, g, lat: float, lon180: float) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    tiers = [(SPECIES_RADIUS_DEG, since, "nearby"), (REGIONAL_RADIUS_DEG, since, "regional"), (REGIONAL_RADIUS_DEG, None, "regional"), (WIDE_RADIUS_DEG, None, "regional")]
    for radius, start, scope in tiers:                    # progressively wider: nearby recent, regional recent, regional older, wide older
        q = select(BiodiversityObservation.species_aphia_id, BiodiversityObservation.species_name, BiodiversityObservation.scientific_name, BiodiversityObservation.latitude,
                   BiodiversityObservation.longitude, BiodiversityObservation.timestamp).where(
            BiodiversityObservation.latitude.between(lat - radius, lat + radius), BiodiversityObservation.longitude.between(lon180 - radius, lon180 + radius))
        rows = db.execute(q.where(BiodiversityObservation.timestamp >= start) if start is not None else q).all()
        if rows:
            break
    if not rows:
        scope = None
    historical = start is None
    earliest = min((r[5] for r in rows), default=None)
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
    n_obs = sum(e["n_records"] for e in by.values())
    latest_rec = max((e["latest"] for e in by.values() if e["latest"]), default=None)
    n_exposed = sum(1 for s in out if s["records_in_heatwave"])
    n_high = sum(1 for s in out if s["highest_risk_level"] in ("HIGH", "CRITICAL"))
    period = (f"{earliest.date()} to {latest_rec}, older records included" if earliest and latest_rec else "older records included") if historical else f"last {WINDOW_DAYS // 365} years"
    note = (f"No stored records within about {WIDE_RADIUS_DEG:g}° of this location. That is a gap in sampling, not evidence that no species are present."
            if not out else f"{len(out)} species with stored OBIS records within about {radius:g}° ({scope} records{', older records included' if historical else ''}; none were stored closer in time or space) "
                            f"({n_exposed} with records inside a current marine heatwave, {n_high} with records in HIGH or CRITICAL risk cells). "
                            "Records show where animals were observed, not their range: the absence of a record is not the absence of the species.") if scope != "nearby" or not out else (
            f"{len(out)} species with stored OBIS records within about {radius:g}° ({n_exposed} with records inside a current marine heatwave, {n_high} with records in HIGH or CRITICAL risk cells). "
            "Records show where animals were observed, not their range: the absence of a record is not the absence of the species.")
    counted = {"observations": n_obs, "distinct_species": len(by), "listed": len(out), "radius_deg": radius, "scope": scope, "historical": historical, "window_days": WINDOW_DAYS,
               "latest_record": latest_rec, "earliest_record": None if earliest is None else earliest.date().isoformat(),
               "label": (f"{'Regional records' if scope == 'regional' else 'Species observations'} within about {radius:g}° of this location ({period}): {n_obs:,} observations; distinct species: {len(by)}"
                         + (f"; the {len(out)} nearest are listed" if len(by) > len(out) else "") + ".") if by else
                        f"No stored biodiversity observations within about {WIDE_RADIUS_DEG:g}° of this location (sampling gap, not absence)."}
    return {"radius_deg": radius, "items": out, "summary": note, "evidence": "observed" if out else "insufficient_coverage", "counted": counted}


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
        + (f"OBIS records of {len(sp)} species lie in cells that are part of this event." if sp else "No OBIS records lie in the cells of this event (limited biodiversity coverage, not evidence of absence)."))


def _data_dates(db: Session, dataset: str, date: str, forecast: dict) -> dict:
    """The day each product of this report refers to, so that no reader assumes they all describe the same day. `aligned` is true only when every product is for the report date."""
    store = es.get_store(dataset)
    hwd = hws.state_for(dataset)
    latest_rec = db.execute(select(func.max(BiodiversityObservation.timestamp))).scalar_one()
    rows = {
        "sst_observation": {"date": date, "latest_available": str(store.dates[-1].date()), "note": "newest observed SST day in the dataset" if date == str(store.dates[-1].date()) else "an earlier day was selected"},
        "anomaly": {"date": date, "baseline": store.train_period},
        "marine_heatwave": {"date": None if hwd is None else hwd.info["latest_date"]},
        "forecast": {"initialised_from": forecast.get("issued_from"), "valid_dates": forecast.get("dates")},
        "species_records": {"latest_record": None if latest_rec is None else latest_rec.date().isoformat(), "window_days": WINDOW_DAYS},
    }
    behind = []
    if rows["marine_heatwave"]["date"] != date:
        behind.append(f"marine-heatwave results are for {rows['marine_heatwave']['date']}")
    if forecast.get("issued_from") != date:
        behind.append(f"the forecast was issued from {forecast.get('issued_from')}")
    return {**rows, "aligned": not behind, "message": ("Every product of this report is for " + date + ".") if not behind else
            "Not every product describes " + date + ": " + "; ".join(behind) + ". The report shows only what applies to the selected date and names what does not."}


def dataset_dates(db: Session, dataset: str | None, date=None) -> dict:
    """The day every product of a dataset refers to (observed SST, anomaly, marine heatwaves, forecast start and valid days, newest species record), for the dashboard."""
    store = es.get_store(dataset)
    ds = store.ref.id
    t = str(store.resolve_date(date).date())
    fc: dict = {"available": False}
    if ds != "ne_pacific":
        try:
            snap, info, _m, _o = forecast_store.load(ds)
            fc = {"available": True, "issued_from": info["latest"]["observed_date"], "dates": info["latest"]["target_dates"]}
        except OutputsUnavailable:
            pass
    return {"dataset": ds, **_data_dates(db, ds, t, fc), "freshness": store.freshness()}


def _attach_external(out: dict, db: Session, lat: float, lon180: float, inp, hw_active, pt: dict) -> None:
    """OBIS biodiversity (with exposure to the heatwave footprint and the predicted anomaly area) and NOAA ERDDAP context (chlorophyll-a, surface currents), both from the cache or fetched in
    the background, and the provenance of every source used. None of this changes the risk score or the forecast."""
    with ThreadPoolExecutor(max_workers=2) as ex:
        fb = ex.submit(obis_service.location_biodiversity, lat, lon180, 4.0)
        fc = ex.submit(ocean_context.location_context, lat, lon180, 4.0)
        bio, ctx = fb.result(), fc.result()
    out["obis"] = biodiversity_view.view(db, bio, lat, inp, hw_active)
    out["context"] = None if ctx is None else {"status": ctx.get("status"), "chlorophyll": ctx.get("chlorophyll"), "currents": ctx.get("currents"), "errors": ctx.get("errors", [])}
    refreshing = (out["obis"] or {}).get("status") == "refreshing" or (ctx or {}).get("status") == "refreshing"
    out["refresh_hint_s"] = 12 if refreshing else None                   # the interface asks again once the background fetch has had time to finish
    dd = out.get("data_dates") or {}
    src = [{"topic": "Sea surface temperature and anomaly", "source": "NOAA OISST v2.1", "dataset": (out.get("provider") or {}).get("description") or "NOAA Optimum Interpolation SST v2.1",
            "observation_date": pt["date"], "spatial_resolution": "0.25°", "temporal_resolution": "daily", "retrieved": _last_refresh()},
           {"topic": "7-day forecast", "source": "Project ConvLSTM (NOAA OISST inputs)", "dataset": (out.get("forecast") or {}).get("model"), "observation_date": (dd.get("forecast") or {}).get("initialised_from"),
            "spatial_resolution": "0.25° grid", "temporal_resolution": "daily, +1 to +7 days", "retrieved": _last_refresh()}]
    if out["obis"] and out["obis"].get("available"):
        p = out["obis"]["provenance"]
        src.append({"topic": "Biodiversity", "source": p["source"], "dataset": p["dataset"], "observation_date": p["observation_dates"], "spatial_resolution": p["spatial_resolution"],
                    "temporal_resolution": p["temporal_resolution"], "retrieved": p["retrieved"]})
    elif ((out.get("species") or {}).get("counted") or {}).get("observations"):
        src.append({"topic": "Biodiversity", "source": "Stored OBIS records (project database)", "dataset": "OBIS occurrences ingested by the project", "observation_date": out["species"]["counted"].get("latest_record"),
                    "spatial_resolution": "point records", "temporal_resolution": "individual observation dates", "retrieved": None})
    for key, topic in (("chlorophyll", "Chlorophyll-a (ecological context)"), ("currents", "Surface currents (physical context)")):
        v = ((out["context"] or {}).get(key)) if out["context"] else None
        if v and v.get("available"):
            src.append({"topic": topic, "source": v["source"], "dataset": v["dataset"], "observation_date": (v.get("latest") or {}).get("date"), "spatial_resolution": v["spatial_resolution"],
                        "temporal_resolution": v["temporal_resolution"], "retrieved": v.get("retrieved")})
    out["sources"] = src


def _last_refresh() -> str | None:
    try:
        f = Path(__file__).resolve().parents[3] / "data" / "refresh_status.json"
        return (json.loads(f.read_text(encoding="utf-8")).get("attempted_at") or "")[:10] or None
    except (OSError, ValueError):
        return None


def _add_outlook(out: dict) -> None:
    """Append "what the forecast suggests" to the anomaly explanation, from the forecast anomalies at this cell: persisting, weakening, strengthening or changing sign.
    Model prediction only; says nothing about a cause."""
    f, ex = out.get("forecast") or {}, (out.get("anomaly") or {}).get("explanation")
    now, fa = (out.get("conditions") or {}).get("anomaly"), f.get("forecast_anomaly")
    if not ex or now is None or not fa or not f.get("available"):
        return
    end, mx = fa[-1], max(abs(x) for x in fa)
    word = "warmer" if now > 0 else "colder"
    if abs(now) < 0.5 and abs(end) < 0.5:
        txt = f"The anomaly is small now ({now:+.1f} °C) and the model keeps it small ({end:+.1f} °C at day +{len(fa)}): conditions stay close to the baseline."
    elif now * end < 0 and abs(end) >= 0.5:
        txt = f"The model expects the anomaly to change sign, from {now:+.1f} °C now to {end:+.1f} °C at day +{len(fa)}."
    elif abs(end) > abs(now) + 0.3:
        txt = f"The model expects the anomaly to strengthen, from {now:+.1f} °C now to {end:+.1f} °C at day +{len(fa)}."
    elif abs(end) < abs(now) - 0.3:
        txt = f"The model expects the anomaly to weaken, from {now:+.1f} °C now to {end:+.1f} °C at day +{len(fa)}, while it stays {word} than the baseline" + ("." if abs(end) >= 0.5 else " only slightly.")
    else:
        txt = f"The model expects the anomaly to persist ({now:+.1f} °C now, {end:+.1f} °C at day +{len(fa)}): {word} than the baseline throughout."
    err = f.get("typical_error_c")
    sec = {"id": "outlook", "title": "What the forecast suggests", "text": txt + " This is a model prediction, not an observation; no physical cause is implied.",
           "bullets": [f"Typical model error is ±{err[-1]:.2f} °C at day +{len(fa)}, so changes smaller than that are not meaningful."] if err else []}
    at = next((k + 1 for k, x in enumerate(ex["sections"]) if x["id"] == "persistence"), len(ex["sections"]))
    ex["sections"].insert(at, sec)


def _forecast(dataset: str, i: int, j: int, sst: float | None, anom_now: float | None = None, hw: dict | None = None, risk: dict | None = None, date: str | None = None) -> dict:
    if dataset == "ne_pacific":
        return {"available": False, "message": "The NE Pacific forecast is shown on the NE Pacific forecast page."}
    try:
        snap, info, metrics, origin = forecast_store.load(dataset)
    except OutputsUnavailable as exc:
        return {"available": False, "message": str(exc)}
    if date is not None and info["latest"]["observed_date"] != date:                   # the same rule the risk score uses: a forecast belongs to the day it was issued from
        return {"available": False, "issued_from": info["latest"]["observed_date"], "message": f"The forecast was issued from {info['latest']['observed_date']}, not from the selected date {date}; "
                                                                                               "it is not shown as if it described this date."}
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
            out.append(f"The current anomaly ({anom_now:+.1f} °C) is expected to {fr.EXPECTED[fr.trajectory(anom_now, anom[-1])]}: the day-{n} forecast anomaly is {anom[-1]:+.1f} °C.")
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
    inp = hw_active = None
    try:
        risk, inp, g = _risk(db, ds, pt["date"], i, j, c["lat"], c["lon"], c, pt["provider"])
        out["risk"] = risk
        hwd = hws.state_for(ds)
        out["species"] = _species(db, inp, {"state": hwd.state} if hwd and hwd.info["latest_date"] == pt["date"] else None, g, c["lat"], lon180)
        hw_active = hwd.state["active"] if hwd and hwd.state is not None and hwd.info["latest_date"] == pt["date"] else None
        if hw.get("inside") and hw.get("event") and hwd is not None and hwd.state is not None and "event_label" in hwd.state:
            _event_relations(db, hw, hwd, g, inp)
    except (OutputsUnavailable, ValueError) as exc:
        out["risk"] = {"status": "unavailable", "message": str(exc)}
        out["species"] = {"items": [], "summary": "Species context unavailable for this dataset.", "evidence": "unavailable", "radius_deg": SPECIES_RADIUS_DEG}
    out["forecast"] = _forecast(ds, i, j, sst, anom, hw, out.get("risk"), pt["date"])
    out["data_dates"] = _data_dates(db, ds, pt["date"], out["forecast"])
    _attach_external(out, db, c["lat"], lon180, inp, hw_active, pt)
    _add_outlook(out)
    report_analysis.build(out, store, pt["date"], i, j)
    out["implications"] = explain_service.implications({"anomaly": anom, "heatwave": hw, "risk": out.get("risk"), "forecast": out["forecast"], "species": out.get("species"), "obis": out.get("obis"), "context": out.get("context"),
                                                          "region": region_name, "date": pt["date"], "lat": c["lat"]})
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
    everything = sorted(pts.values(), key=lambda e: (e["conservation_status"] not in ("CR", "EN", "VU", "NT"), -e["n_records"]))
    items = everything[:2500]
    return {"dataset": inp.dataset, "date": inp.date, "region": {"id": reg.id, "name": reg.name}, "items": items, "heatwave_computed": hw_on,
            "summary": {"points": len(items), "points_total": len(everything), "species": len({e["scientific_name"] for e in everything}), "records": sum(e["n_records"] for e in everything),
                        "window_days": WINDOW_DAYS, "records_definition": f"stored OBIS observations in this region within the last {WINDOW_DAYS // 365} years; species = distinct species among them",
                        "points_in_heatwave": sum(1 for e in everything if e["in_heatwave"]), "points_high_risk": sum(1 for e in everything if e["risk_level"] in ("HIGH", "CRITICAL")),
                        "conservation_sensitive_species": len({e["scientific_name"] for e in everything if e["conservation_status"] in CONSERVATION_SENSITIVE}),
                        "threatened_in_heatwave": len({e["scientific_name"] for e in everything if e["in_heatwave"] and e["conservation_status"] in ("CR", "EN", "VU", "NT")}),
                        "with_alert": len({e["scientific_name"] for e in everything if e["alert_severity"]})},
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
        return {**base, "available": False, "message": "No stored records inside this dataset in the last two years: limited coverage, so exposure cannot be assessed from stored records (not evidence that the species is absent)."}
    n = len(an)
    x = {**base, "available": True, "n_records": n, "n_cells": len(cells), "latest_record": latest, "latitude_range": [min(lats), max(lats)], "mean_anomaly_c": float(np.mean(an)),
         "max_anomaly_c": float(max(an, key=abs)), "share_anomaly_1c": sum(1 for v in an if abs(v) >= 1.0) / n, "heatwave_available": hw_on,
         "share_in_heatwave": inhw / n if hw_on else None, "share_high_risk": (sum(1 for v in rl if v in ("HIGH", "CRITICAL")) / len(rl)) if rl else None,
         "highest_risk_level": max(rl, key=levels.index) if rl else None, "top_region": max(regions, key=regions.get) if regions else None,
         "mean_forecast_anomaly_c": fc_mean, "alert_severity": alert_sev}
    x["explanation"] = explain_service.explain_species({**x, "share_in_heatwave": x["share_in_heatwave"] or 0.0})
    return x
