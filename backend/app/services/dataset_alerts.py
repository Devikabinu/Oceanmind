"""Alerts for datasets other than the NE Pacific export (e.g. `pacific`), raised from the dataset's precomputed marine-heatwave events and its ecological-risk
areas. Same Alert table, same severity scale and same stable-key de-duplication as the NE alerts (jobs/publish_outputs.py); the dataset, region, event and
location are stored in `details` so an alert can link back to its heatwave, map region and risk cell. Nothing is invented: species come from stored OBIS records,
conservation categories from the species table, and a dataset whose SST is modelled says so in the alert."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertStatus
from app.services import explain_service, geo_regions as geo, heatwave_service as hws, risk_service, species_service
from app.services.taxonomy import CONSERVATION_SENSITIVE

CATEGORY_SEVERITY = {1: AlertSeverity.MEDIUM, 2: AlertSeverity.HIGH, 3: AlertSeverity.CRITICAL, 4: AlertSeverity.CRITICAL}
SEV_BY_NAME = {n: AlertSeverity[n] for n in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}
REGION_ORDER = ["east_asia", "southeast_asia", "australia_new_zealand", "melanesia", "micronesia", "polynesia", "western_pacific", "central_pacific", "eastern_pacific"]
MAX_EVENT_ALERTS = 10
MAX_RISK_ALERTS = 5


def region_for(lat: float, lon: float) -> tuple[str, str]:
    """(id, name) of the most specific named region containing the point, else the dataset-wide region."""
    for rid in REGION_ORDER:
        if bool(geo.region_mask(geo.get_region(rid), [lat], [lon])[0, 0]):
            return rid, geo.get_region(rid).name
    return "pacific", geo.get_region("pacific").name


def regions_containing(lat: float, lon: float) -> list[str]:
    """Every region id whose area contains the point (an alert is found under each region it lies in)."""
    return [rid for rid, r in geo.REGIONS.items() if bool(geo.region_mask(r, [lat], [lon])[0, 0])]


def _ts(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def _find(db: Session, key: str):
    return db.execute(select(Alert).where(Alert.details["key"].as_string() == key)).scalar_one_or_none()


def _lon180(lon: float) -> float:
    return ((lon + 180) % 360) - 180


def generate(db: Session, dataset: str) -> dict:
    d = hws.data(dataset)
    info = d.info
    day = info["latest_date"]
    src = info.get("source") or {}
    generated = info.get("is_observational") is False
    provider = src.get("provider_id") or info["data_source"]
    sources = [f"{provider} ({'modelled dataset' if generated else 'observations'})", "OBIS (species records)"]
    created = {"MARINE_HEATWAVE": 0, "ECOLOGICAL_RISK": 0, "SST_ANOMALY": 0, "SST_FORECAST_HEAT": 0, "REFRESHED": 0}

    def add(alert_type, severity, lat, lon, message, details):
        existing = _find(db, details["key"])
        if existing is not None:
            if existing.details != details or existing.message != message:
                existing.details, existing.message = details, message
                created["REFRESHED"] += 1
            return
        db.add(Alert(alert_type=alert_type, severity=severity, latitude=lat, longitude=lon, timestamp=_ts(day), message=message, status=AlertStatus.NEW, details=details))
        created[alert_type] += 1

    inp = risk_service.inputs_for(dataset, day)
    overlap = risk_service.species_overlap_blocks(db, inp)
    grids = risk_service.factor_grids(inp, overlap)

    # 1. marine heatwaves (same worth-an-alert rule as the NE Pacific alerts)
    for ev in hws.events_for(dataset)[:MAX_EVENT_ALERTS]:
        c = ev["centroid"]
        from app.services import location_report
        sp = location_report.species_in_event_footprint(db, dataset, ev["id"], 8)
        if sp is None:                                          # no footprint stored for this dataset: the coarser bounding-box statement
            species: dict[tuple, dict] = {}
            for seg in hws.bbox_segments(ev["bbox"]):
                for s in species_service.species_in_bbox(db, seg, limit=8):
                    k = (s["aphia_id"], s["scientific_name"])
                    if k in species:
                        species[k]["n_records"] += s["n_records"]
                    else:
                        species[k] = dict(s)
            sp = sorted(species.values(), key=lambda s: -s["n_records"])[:8]
        sensitive = [x for x in sp if x.get("iucn_category") in CONSERVATION_SENSITIVE]
        if ev["area_km2"] < 50_000 and ev["category"] < 3 and not sensitive:
            continue
        lon180 = c.get("lon_180", _lon180(c["lon"]))
        rid, rname = region_for(c["lat"], c["lon"])
        cell = risk_service.inputs_for(dataset, day).cell(c["lat"], c["lon"])
        risk_info = None
        if cell is not None:
            a = risk_service.cell_assessment(inp, cell[0], cell[1], overlap, grids)
            risk_info = {k: a[k] for k in ("score", "level", "status", "evidence_completeness", "biodiversity_evidence", "factors")}
        bio = "observed" if sp else "insufficient_coverage"
        reasons = [
            f"SST has been above the seasonal 90th percentile for {ev['duration_days']} days (since {ev['start_date']}).",
            f"Current anomaly {ev['current_anomaly_c']:+.1f} degC, peak {ev['max_anomaly_c']:+.1f} degC ({ev['category_name']}); cumulative intensity {ev.get('cumulative_intensity_c_days', 0):.0f} degC-days.",
            f"Affected area about {ev['area_km2']:,.0f} km2; warmer than {ev['historical_percentile']:.0f}% of baseline values for this date.",
            (f"{len(sp)} species have OBIS records in the area ({len(sensitive)} listed VU/EN/CR by their source)." if sp
             else "No stored species records overlap this area (limited biodiversity coverage; that does not mean no animals are present)."),
        ]
        p7 = ev.get("forecast_still_above_p90_day7")
        if p7 is not None:
            reasons.append(f"Forecast (model prediction): {p7 * 100:.0f}% of the event area is still above the heatwave threshold on day 7, so the condition {'may persist' if p7 >= 0.5 else 'may ease'}.")
        if risk_info and risk_info["level"]:
            reasons.append(f"Ecological risk at the event centre: {risk_info['level']} (score {risk_info['score']:.2f}, {risk_info['evidence_completeness'] * 100:.0f}% of the methodology weight available).")
        narrative = explain_service.explain_event(ev, info, sp, bio)
        key = f"{dataset}:mhw:{ev['start_date']}:{round(c['lat'] / 2)}:{round(lon180 / 2)}"
        add("MARINE_HEATWAVE", CATEGORY_SEVERITY[ev["category"]], c["lat"], lon180,
            f"Marine heatwave ({dataset}, project definition): {ev['category_name']}, {ev['duration_days']} days, {ev['area_km2']:,.0f} km2, anomaly {ev['current_anomaly_c']:+.1f} degC in the {rname}",
            {"key": key, "dataset": dataset, "driver": "Marine heatwave", "region": rname, "region_id": rid, "regions": regions_containing(c["lat"], c["lon"]), "event_id": ev["id"], "date": day,
             "location": {"lat": c["lat"], "lon_180": lon180}, "reasons": reasons, "species": sp, "conservation_sensitive": sensitive,
             "biodiversity_evidence": bio, "risk": risk_info, "data_sources": sources, "provider": src, "is_observational": not generated,
             "classification": "DERIVED METRIC: simplified Hobday-style definition; not an official classification" + ("; computed from a modelled SST dataset" if generated else ""),
             "recommendation": "Monitoring priority: review the event, its footprint and the species with records in this area.",
             "evidence": {k: v for k, v in ev.items() if k != "timeline"}, "narrative": narrative,
             "evidence_summary": [
                 {"label": "Maximum anomaly", "value": f"{ev['max_anomaly_c']:+.1f} °C"},
                 {"label": "Current anomaly", "value": f"{ev['current_anomaly_c']:+.1f} °C"},
                 {"label": "Duration", "value": f"{ev['duration_days']} days (since {ev['start_date']})"},
                 {"label": "Affected area", "value": f"{ev['area_km2']:,.0f} km²"},
                 {"label": "Cumulative intensity", "value": f"{ev.get('cumulative_intensity_c_days', 0):.0f} °C·days"},
                 {"label": "Ecological risk", "value": (f"{risk_info['level']} ({risk_info['score']:.2f})" if risk_info and risk_info["level"] else "not assessed")},
                 {"label": "Forecast, day 7 (prediction)", "value": (f"{p7 * 100:.0f}% of area still above threshold" if p7 is not None else "not available")},
                 {"label": "Biodiversity overlap", "value": f"{len(sp)} species with records" if sp else "limited coverage"},
                 {"label": "Conservation-sensitive species", "value": str(len(sensitive)) if sp else "not confirmed"}]})

    # 2. highest ecological-risk 2x2 degree areas
    from app.api.v1.ecological_risk import risk_areas
    for r in risk_areas(min_level="HIGH", limit=MAX_RISK_ALERTS, region="all", dataset=dataset, date=day, db=db)["items"]:
        lon180 = r.get("lon_180", _lon180(r["lon"]))
        rid, rname = region_for(r["lat"], r["lon"])
        cell = inp.cell(r["lat"], r["lon"])
        a = risk_service.cell_assessment(inp, cell[0], cell[1], overlap, grids) if cell else None
        reasons = a["reasons"] if a else []
        add("ECOLOGICAL_RISK", SEV_BY_NAME[r["level"]], r["lat"], lon180,
            f"Ecological risk {r['level']} (score {r['score']:.2f}) in a 2x2 degree area of the {rname}; main driver {explain_service.FACTOR_LABEL.get(r['top_driver'], r['top_driver'])}",
            {"key": f"{dataset}:risk:{day}:{r['lat']}:{lon180}", "dataset": dataset, "driver": "Ecological risk", "region": rname, "region_id": rid, "regions": regions_containing(r["lat"], r["lon"]), "date": day,
             "location": {"lat": r["lat"], "lon_180": lon180}, "reasons": reasons, "species": [], "biodiversity_evidence": a["biodiversity_evidence"] if a else None,
             "risk": {"score": r["score"], "level": r["level"], "factors": r["factors"], "top_driver": r["top_driver"]}, "data_sources": sources, "provider": src,
             "is_observational": not generated, "classification": "DERIVED METRIC: project environmental risk indicator (potential exposure, not evidence of harm)",
             "recommendation": "Monitoring priority only; open the risk cell for the factor breakdown and its explanation.", "evidence": {"factors": r["factors"], "bbox": r["bbox"]},
             "narrative": explain_service.explain_risk_cell({**(a or {}), "dataset": dataset, "date": day, "source": {"is_observational": not generated},
                                                             "cell": {"lat": r["lat"], "lon": r["lon"], "lon_180": lon180}}) if a else None,
             "evidence_summary": [{"label": "Risk score", "value": f"{r['score']:.2f} ({r['level']})"},
                                  {"label": "Main driver", "value": r["top_driver"]},
                                  {"label": "Factors (0–1)", "value": ", ".join(f"{k} {v:.2f}" for k, v in r["factors"].items())},
                                  {"label": "Unavailable factors", "value": ", ".join(inp.unavailable) or "none"}]})
    # 3. conservation-relevant species with records inside a current marine heatwave (only where records and the heatwave overlap)
    from app.services import location_report
    layer = location_report.species_layer(db, dataset, "pacific", day)
    sev = {"CR": AlertSeverity.CRITICAL, "EN": AlertSeverity.HIGH, "VU": AlertSeverity.MEDIUM, "NT": AlertSeverity.LOW}
    by: dict = {}
    for p in layer["items"]:
        if p["conservation_status"] in sev and p["in_heatwave"] and p["aphia_id"]:
            by.setdefault(p["aphia_id"], []).append(p)
    for aid, pts in sorted(by.items(), key=lambda kv: (list(sev).index(kv[1][0]["conservation_status"]), -sum(q["n_records"] for q in kv[1])))[:8]:
        x = location_report.species_exposure(db, dataset, aid, day)
        if not x.get("available"):
            continue
        p0 = pts[0]
        la = float(np.mean([q["lat"] for q in pts]))
        lo = float(np.mean([q["lon_180"] for q in pts]))
        rid, rname = region_for(la, float(((lo + 360) % 360)))
        name = p0["common_name"] or p0["scientific_name"]
        cs = p0["conservation_status"]
        add("ECOLOGICAL_RISK", sev[cs], la, lo,
            f"Species exposure: {name} ({cs}) has {x['share_in_heatwave'] * 100:.0f}% of its {x['n_records']} stored records inside a current marine heatwave",
            {"key": f"{dataset}:species:{aid}:{day}", "dataset": dataset, "driver": "Species exposure", "region": rname, "region_id": rid, "regions": regions_containing(la, float(((lo + 360) % 360))),
             "date": day, "location": {"lat": la, "lon_180": lo}, "species": [{"aphia_id": aid, "scientific_name": p0["scientific_name"], "common_name": p0["common_name"]}],
             "conservation_sensitive": [{"aphia_id": aid, "scientific_name": p0["scientific_name"], "common_name": p0["common_name"], "iucn_category": cs}] if x["conservation_sensitive"] else [],
             "biodiversity_evidence": "observed", "risk": {"score": None, "level": x["highest_risk_level"]}, "data_sources": sources, "provider": src, "is_observational": not generated,
             "reasons": [s["text"] for s in x["explanation"]["sections"]], "classification": "DERIVED METRIC: potential exposure of stored OBIS records (observations, not a species range); not evidence of harm",
             "recommendation": "Review the heatwave and the species' recorded locations on the map; monitoring priority only.", "narrative": x["explanation"], "evidence": {k: x[k] for k in ("n_records", "n_cells", "share_in_heatwave", "share_high_risk", "mean_anomaly_c")},
             "evidence_summary": [{"label": "Conservation status", "value": f"{cs} ({x['conservation_source']})"}, {"label": "Records", "value": f"{x['n_records']} in {x['n_cells']} cells"},
                                  {"label": "Records inside a heatwave", "value": f"{x['share_in_heatwave'] * 100:.0f}%"}, {"label": "Highest risk level at records", "value": x["highest_risk_level"] or "not assessed"},
                                  {"label": "Mean anomaly at records", "value": f"{x['mean_anomaly_c']:+.1f} °C"}]})
    _anomaly_alerts(db, dataset, day, add, sources, src, generated)
    _forecast_alerts(db, dataset, day, add, sources, src, generated)
    db.commit()
    return created


EXTREME_ANOMALY_C = 3.0
MAX_EXTREME_ALERTS = 5          # the strongest areas only: an alert list that grows with every warm cell stops being read
MAX_PERSISTENT_ALERTS = 3
PERSISTENT_ALERT_DAYS = 21


def _anomaly_alerts(db: Session, dataset: str, day: str, add, sources, src, generated) -> None:
    """Extreme, rapidly developing and persistent anomalies, from the anomaly analysis of the dataset's latest date. Each alert says how unusual the value is compared with the
    same cell's own history and links to the exact place on the map."""
    from app.services import anomaly_analysis
    try:
        a = anomaly_analysis.analysis(dataset, day, "pacific", top=8)
    except Exception:  # noqa: BLE001 - a dataset without anomaly cubes simply raises no anomaly alerts
        return

    def one(kind, severity, c, headline, reasons, evidence):
        lon180 = c["lon_180"]
        rid, rname = c["region"]["id"], c["region"]["name"]
        add("SST_ANOMALY", severity, c["lat"], lon180, f"{headline} in the {rname}",
            {"key": f"{dataset}:anomaly:{kind}:{day}:{round(c['lat'])}:{round(lon180)}", "dataset": dataset, "driver": "SST anomaly", "kind": kind, "region": rname, "region_id": rid,
             "regions": regions_containing(c["lat"], c["lon"]), "date": day, "location": {"lat": c["lat"], "lon_180": lon180}, "reasons": reasons, "species": [],
             "biodiversity_evidence": None, "risk": None, "data_sources": sources, "provider": src, "is_observational": not generated,
             "classification": "DERIVED METRIC: departure of sea surface temperature from the baseline climatology; it states how unusual the temperature is, not why",
             "recommendation": "Open the location report for the anomaly interpretation, heatwave status, ecological risk and nearby species.",
             "evidence": evidence, "evidence_summary": [{"label": k, "value": v} for k, v in evidence.items()]})

    n_extreme = n_persistent = 0
    for c in sorted(a["strongest_warm"] + a["strongest_cold"], key=lambda c: -abs(c["anomaly_c"])):
        if n_extreme >= MAX_EXTREME_ALERTS:
            break
        v, pct = c["anomaly_c"], c["historical_percentile"]
        extreme_hist = pct is not None and c["historical_samples"] >= 100 and (pct >= 99.5 or pct <= 0.5)
        if abs(v) < EXTREME_ANOMALY_C and not (extreme_hist and abs(v) >= 2.0):
            continue
        sev = AlertSeverity.CRITICAL if abs(v) >= 4 else AlertSeverity.HIGH if abs(v) >= EXTREME_ANOMALY_C else AlertSeverity.MEDIUM
        side = "warmer" if v > 0 else "colder"
        rank = f"{side} than {pct if v > 0 else 100 - pct:.1f}% of {c['historical_samples']:,} comparable days at this location" if pct is not None else "history too short to rank"
        n_extreme += 1
        one("extreme", sev, c, f"Extreme SST anomaly {v:+.1f} degC", [f"The anomaly is {v:+.1f} degC from the baseline climatology.", f"This is {rank}.",
            "The data show how unusual the temperature is; they do not establish a cause."], {"Anomaly": f"{v:+.1f} °C", "Historical rank": rank})
    for c in a.get("rapidly_developing", [])[:3]:
        sev = AlertSeverity.HIGH if abs(c["change_7d_c"]) >= 2.5 else AlertSeverity.MEDIUM
        one("rapid", sev, c, f"Rapidly {c['direction']} SST: {c['change_7d_c']:+.1f} degC in 7 days (anomaly now {c['anomaly_c']:+.1f})",
            [f"The anomaly changed by {c['change_7d_c']:+.1f} degC over the last 7 days and is now {c['anomaly_c']:+.1f} degC.", "Rapid change does not by itself indicate a heatwave or its cause."],
            {"Change in 7 days": f"{c['change_7d_c']:+.1f} °C", "Anomaly now": f"{c['anomaly_c']:+.1f} °C"})
    for c in a["persistent"]:
        if c["days"] < PERSISTENT_ALERT_DAYS or abs(c["anomaly_c"]) < 1.5:
            continue
        if n_persistent >= MAX_PERSISTENT_ALERTS:
            break
        n_persistent += 1
        sev = AlertSeverity.HIGH if c["days"] >= 45 else AlertSeverity.MEDIUM
        plus = "+" if c["capped"] else ""
        one("persistent", sev, c, f"Persistent {c['direction']} anomaly: {c['days']}{plus} days beyond 1 degC (now {c['anomaly_c']:+.1f})",
            [f"The anomaly has stayed beyond 1 degC on the {c['direction']} side for {c['days']}{plus} consecutive days.", f"It is {c['anomaly_c']:+.1f} degC today."],
            {"Days beyond 1 °C": f"{c['days']}{plus}", "Anomaly now": f"{c['anomaly_c']:+.1f} °C"})


def _forecast_alerts(db: Session, dataset: str, day: str, add, sources, src, generated) -> None:
    """Where the model predicts the anomaly to be clearly larger on day 7 than it is now. The wording keeps these as predictions."""
    from app.services import anomaly_analysis, environment_store as es, forecast_store
    try:
        snap, finfo, _m, _o = forecast_store.load(dataset)
        if finfo["latest"]["observed_date"] != day:
            return
        store = es.get_store(dataset)
        cur, status, _t = store.native_layer("anomaly", day)
    except Exception:  # noqa: BLE001 - no forecast for this dataset or date
        return
    fc = snap["latest_forecast"][-1] - snap["latest_climatology"][-1]
    change = np.where(np.isfinite(fc) & np.isfinite(cur), fc - cur, np.nan)
    test = np.where((fc >= 2.0) & (change >= 1.0), change, np.nan)
    for i, j, v in anomaly_analysis._thinned(test, store.lat, store.lon, 4, True):
        la, lo = float(store.lat[i]), float(store.lon[j])
        lon180 = _lon180(lo)
        rid, rname = region_for(la, lon180)
        sev = AlertSeverity.HIGH if v >= 2.0 else AlertSeverity.MEDIUM
        add("SST_FORECAST_HEAT", sev, la, lon180,
            f"Forecast (model prediction): anomaly rising to {float(fc[i, j]):+.1f} degC by day 7 in the {rname}",
            {"key": f"{dataset}:forecast:{day}:{round(la)}:{round(lon180)}", "dataset": dataset, "driver": "Forecast", "region": rname, "region_id": rid, "regions": regions_containing(la, lo), "date": day,
             "location": {"lat": la, "lon_180": lon180},
             "reasons": [f"The model predicts an anomaly of {float(fc[i, j]):+.1f} degC on day 7, {v:+.1f} degC more than the observed {float(cur[i, j]):+.1f} degC today.",
                         "This is a prediction from the project model, not an observation; the model was trained on the northeast Pacific, so its skill elsewhere is limited."],
             "species": [], "biodiversity_evidence": None, "risk": None, "data_sources": sources + ["ConvLSTM forecast (model output)"], "provider": src, "is_observational": not generated,
             "classification": "MODEL PREDICTION: not an observation",
             "recommendation": "Compare with the persistence forecast and the model's validation limits in the location report.",
             "evidence": {"Forecast anomaly, day 7": f"{float(fc[i, j]):+.1f} °C", "Observed anomaly today": f"{float(cur[i, j]):+.1f} °C"},
             "evidence_summary": [{"label": "Forecast anomaly, day 7 (prediction)", "value": f"{float(fc[i, j]):+.1f} °C"}, {"label": "Observed anomaly today", "value": f"{float(cur[i, j]):+.1f} °C"}]})
