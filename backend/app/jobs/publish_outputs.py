"""Publish the ML pipeline's real outputs into the database tables the API/UI read (CONTRACTS.md), and raise explainable
alerts from them. Nothing is invented: every row is derived from the NOAA OISST export, the ConvLSTM forecast, real OBIS
records already in the database, or the project's documented indicators. Safe to re-run (new dataset per export date;
alerts de-duplicated by a stable key in `details.key`).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models.alert import Alert
from app.models.anomaly_detection import AnomalyDetection
from app.models.biodiversity_observation import BiodiversityObservation
from app.models.data_quality_report import DataQualityReport
from app.models.dataset import Dataset
from app.models.ecological_risk_score import EcologicalRiskScore
from app.models.enums import AlertSeverity, AlertStatus, DatasetKind, IngestionJobStatus, RiskLevel
from app.models.ingestion_job import IngestionJob
from app.models.ocean_observation import OceanObservation
from app.models.species import Species
from app.models.sst_forecast import SSTForecast
from app.repositories.data_source_repository import DataSourceRepository
from app.services import monitor_service, risk_service, species_service
from app.services.taxonomy import CONSERVATION_SENSITIVE
from app.services.environment import Env, env as load_env

logger = logging.getLogger("ocean_platform")

STRIDE = 4  # 1 degree sample of the 0.25 degree grid
ANOMALY_THRESHOLD_C = 1.0
CATEGORY_SEVERITY = {1: AlertSeverity.MEDIUM, 2: AlertSeverity.HIGH, 3: AlertSeverity.CRITICAL, 4: AlertSeverity.CRITICAL}
SEV_BY_NAME = {"LOW": AlertSeverity.LOW, "MEDIUM": AlertSeverity.MEDIUM, "HIGH": AlertSeverity.HIGH, "CRITICAL": AlertSeverity.CRITICAL}
RISK_BY_NAME = {n: RiskLevel[n] for n in ("LOW", "MEDIUM", "HIGH", "CRITICAL")}
SOURCES_OBS = "NOAA OISST v2.1 (observed, processed study-region export)"
SOURCES_FC = "Project ConvLSTM forecast (model output)"


def region_label(lat: float, lon: float) -> str:
    return f"NE Pacific study region near {abs(lat):.1f}{'N' if lat >= 0 else 'S'}, {abs(lon):.1f}{'W' if lon < 0 else 'E'}"


def _ts(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def _geom(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


# --- observations / anomalies / forecasts -------------------------------------------------------------------------------
def _publish_environment(db: Session, e: Env, user_id: uuid.UUID, days: int) -> dict:
    latest = e.info["latest"]
    dates = [str(d) for d in e.hist["dates"]][-days:]
    name = f"NOAA OISST processed study-region export {dates[0]}_{dates[-1]} (1 degree sample)"
    if db.execute(select(Dataset.id).where(Dataset.name == name)).first():
        return {"environment": "already published", "dataset": name}
    source = DataSourceRepository(db).get_by_name("NOAA OISST v2.1")
    if source is None:
        raise RuntimeError("NOAA data source is not registered (start the API once to seed data sources)")
    b = e.bounds
    ds = Dataset(data_source_id=source.id, name=name, kind=DatasetKind.ENVIRONMENTAL,
                 temporal_start=_ts(dates[0]), temporal_end=_ts(dates[-1]), min_latitude=b["lat_min"], max_latitude=b["lat_max"],
                 min_longitude=b["lon_min"], max_longitude=b["lon_max"], record_count=0)
    db.add(ds)
    db.flush()
    ii = [i for i in range(STRIDE // 2, len(e.lat), STRIDE)]
    jj = [j for j in range(STRIDE // 2, len(e.lon), STRIDE)]
    obs_rows, anom_rows, obs_ids = [], [], {}
    n_hist = e.hist["sst_c"].shape[0]
    for off, day in enumerate(dates):
        k = n_hist - len(dates) + off
        doy = _ts(day).timetuple().tm_yday
        for i in ii:
            for j in jj:
                if not e.is_ocean(i, j):
                    continue
                raw = int(e.hist["sst_c"][k, i, j])
                if raw == -32768:
                    continue
                sst = raw / 100.0
                clim = int(e.hist["clim_c"][doy - 1, i, j]) / 100.0
                anom = sst - clim
                oid = uuid.uuid4()
                lat, lon = float(e.lat[i]), float(e.lon[j])
                obs_ids[(day, i, j)] = oid
                obs_rows.append({"id": oid, "dataset_id": ds.id, "timestamp": _ts(day), "latitude": lat, "longitude": lon,
                                 "sst": round(sst, 2), "sst_anomaly": round(anom, 2),
                                 "source_record_id": f"oisst-processed:{day}:{i}:{j}", "geometry": _geom(lat, lon)})
                anom_rows.append({"id": uuid.uuid4(), "observation_id": oid, "timestamp": _ts(day), "latitude": lat, "longitude": lon,
                                  "anomaly_score": round(min(abs(anom) / 3.0, 1.0), 3),
                                  "is_anomaly": abs(anom) >= ANOMALY_THRESHOLD_C,
                                  "model_version": f"sst-climatology-departure-v1 (|anomaly| >= {ANOMALY_THRESHOLD_C:g} degC vs 2012-2023)"})
    for chunk in range(0, len(obs_rows), 5000):
        db.execute(insert(OceanObservation), obs_rows[chunk:chunk + 5000])
    db.flush()
    for chunk in range(0, len(anom_rows), 5000):
        db.execute(insert(AnomalyDetection), anom_rows[chunk:chunk + 5000])
    ds.record_count = len(obs_rows)

    ckpt = (e.info.get("checkpoint") or {}).get("epoch")
    version = f"convlstm-best-epoch{ckpt}-issued-{latest['observed_date']}"
    fc_rows = []
    for h, tday in enumerate(latest["target_dates"]):
        for i in ii:
            for j in jj:
                if not e.is_ocean(i, j) or np.isnan(e.z["latest_forecast"][h, i, j]):
                    continue
                fc_rows.append({"id": uuid.uuid4(), "dataset_id": ds.id, "timestamp": _ts(tday), "latitude": float(e.lat[i]),
                                "longitude": float(e.lon[j]), "predicted_sst": round(float(e.z["latest_forecast"][h, i, j]), 2),
                                "forecast_horizon_days": h + 1, "model_version": version})
    for chunk in range(0, len(fc_rows), 5000):
        db.execute(insert(SSTForecast), fc_rows[chunk:chunk + 5000])

    now = datetime.now(timezone.utc)
    job = IngestionJob(data_source_id=source.id, dataset_id=ds.id, created_by=user_id, status=IngestionJobStatus.COMPLETED,
                       params={"origin": "processed study-region export (oceanmind_model export-dashboard)", "days": days,
                               "sample": f"{STRIDE * 0.25:g} degree stride"},
                       records_read=len(obs_rows), records_valid=len(obs_rows), started_at=now, completed_at=now, execution_time_seconds=0.0)
    db.add(job)
    db.flush()
    db.add(DataQualityReport(dataset_id=ds.id, ingestion_job_id=job.id, records_read=len(obs_rows), records_valid=len(obs_rows),
                             records_rejected=0, missing_values=0, duplicate_records=0, invalid_coordinates=0, invalid_timestamps=0,
                             invalid_sst=0, outliers=0, schema_mismatches=0,
                             details={"note": "Values come from the already-validated processed NOAA OISST cubes; land and missing cells are omitted."}))
    db.commit()
    return {"environment": "published", "dataset": name, "ocean_observations": len(obs_rows), "anomaly_detections": len(anom_rows),
            "sst_forecasts": len(fc_rows), "dataset_id": ds.id}


# --- per-observation ecological risk -------------------------------------------------------------------------------------
def _publish_risk(db: Session, e: Env, max_rows: int = 1500, window_days: int = 180) -> dict:
    latest_obs = db.execute(select(func.max(BiodiversityObservation.timestamp))).scalar_one()
    if latest_obs is None:
        return {"risk": "no biodiversity observations loaded"}
    already = {r[0] for r in db.execute(select(EcologicalRiskScore.biodiversity_observation_id)).all()}
    b = e.bounds
    rows = db.execute(
        select(BiodiversityObservation).where(
            BiodiversityObservation.timestamp >= latest_obs - timedelta(days=window_days),
            BiodiversityObservation.latitude.between(b["lat_min"], b["lat_max"]),
            BiodiversityObservation.longitude.between(b["lon_min"], b["lon_max"]),
        ).order_by(BiodiversityObservation.timestamp.desc()).limit(max_rows * 2)
    ).scalars().all()
    overlap = risk_service.species_overlap_blocks(db, e)
    grids = risk_service.factor_grids(e, overlap)
    out = []
    for o in rows:
        if o.id in already:
            continue
        c = e.cell(o.latitude, o.longitude)
        if c is None or not e.is_ocean(*c):
            continue
        a = risk_service.cell_assessment(e, c[0], c[1], overlap, grids)
        out.append({"id": uuid.uuid4(), "biodiversity_observation_id": o.id, "timestamp": o.timestamp, "latitude": o.latitude,
                    "longitude": o.longitude, "risk_score": a["score"], "risk_level": RISK_BY_NAME[a["level"]],
                    "contributing_factors": {
                        "method": risk_service.METHODOLOGY["name"], "basis": "conditions on the latest observed date at the record location "
                        "(potential exposure, not conditions at the time of the record)", "conditions_date": e.info["latest"]["observed_date"],
                        "species": o.species_name or o.scientific_name,
                        "factors": {f["factor"]: f["value"] for f in a["factors"]}, "reasons": a["reasons"]}})
        if len(out) >= max_rows:
            break
    for chunk in range(0, len(out), 2000):
        db.execute(insert(EcologicalRiskScore), out[chunk:chunk + 2000])
    db.commit()
    return {"risk": "published", "ecological_risk_scores": len(out)}


# --- alerts ----------------------------------------------------------------------------------------------------------------
def _find(db: Session, key: str):
    return db.execute(select(Alert).where(Alert.details["key"].as_string() == key)).scalar_one_or_none()


def _nearest_anomaly(db: Session, lat: float, lon: float, day: str):
    return db.execute(
        select(AnomalyDetection.id).where(AnomalyDetection.timestamp == _ts(day))
        .order_by(func.abs(AnomalyDetection.latitude - lat) + func.abs(AnomalyDetection.longitude - lon)).limit(1)
    ).scalar_one_or_none()


def _nearest_forecast(db: Session, lat: float, lon: float, day: str):
    return db.execute(
        select(SSTForecast.id).where(SSTForecast.timestamp == _ts(day), SSTForecast.forecast_horizon_days == 7)
        .order_by(func.abs(SSTForecast.latitude - lat) + func.abs(SSTForecast.longitude - lon)).limit(1)
    ).scalar_one_or_none()


def generate_alerts(db: Session, e: Env) -> dict:
    latest = e.info["latest"]
    day = latest["observed_date"]
    created = {"MARINE_HEATWAVE": 0, "SST_ANOMALY": 0, "SST_FORECAST_HEAT": 0, "ECOLOGICAL_RISK": 0}
    refreshed = {"count": 0}

    def add(alert_type, severity, lat, lon, ts, message, details, **rel):
        existing = _find(db, details["key"])
        if existing is not None:
            # same event seen again: refresh the evidence/text in place, never touch status or resolution
            if existing.details != details or existing.message != message:
                existing.details, existing.message = details, message
                refreshed["count"] += 1
            return
        db.add(Alert(alert_type=alert_type, severity=severity, latitude=lat, longitude=lon, timestamp=ts, message=message,
                     status=AlertStatus.NEW, details=details, **rel))
        created[alert_type] += 1

    # 1. marine heatwaves
    if e.hwinfo is not None:
        for ev in e.hwinfo["events"][:6]:
            c = ev["centroid"]
            species = species_service.species_in_bbox(db, ev["bbox"], limit=8)
            sensitive = [x for x in species if x.get("iucn_category") in CONSERVATION_SENSITIVE]
            # worth an alert if large, severe, or overlapping species a source lists as VU/EN/CR
            if ev["area_km2"] < 50_000 and ev["category"] < 3 and not sensitive:
                continue
            reasons = [
                f"SST has been above the seasonal 90th percentile for {ev['duration_days']} days (since {ev['start_date']}).",
                f"Current anomaly {ev['current_anomaly_c']:+.1f} degC, peak {ev['max_anomaly_c']:+.1f} degC ({ev['category_name']}).",
                f"Affected area about {ev['area_km2']:,.0f} km2; warmer than {ev['historical_percentile']:.0f}% of baseline values for this date.",
            ]
            p7 = ev.get("forecast_still_above_p90_day7")
            if p7 is not None:
                reasons.append(f"Model forecast: {p7 * 100:.0f}% of the area is still above the threshold on day 7 (model output).")
            reasons.append(
                f"{len(species)} species have OBIS records in the area ({len(sensitive)} conservation-sensitive: IUCN VU/EN/CR as reported by the source)."
                if species else "No stored species records overlap this area (that does not mean no animals are present).")
            add("MARINE_HEATWAVE", CATEGORY_SEVERITY[ev["category"]], c["lat"], c["lon"], _ts(day),
                f"Marine heatwave (project definition): {ev['category_name']}, {ev['duration_days']} days, {ev['area_km2']:,.0f} km2, "
                f"anomaly {ev['current_anomaly_c']:+.1f} degC near {abs(c['lat']):.1f}N, {abs(c['lon']):.1f}W",
                {"key": f"mhw:{ev['start_date']}:{round(c['lat'] / 2)}:{round(c['lon'] / 2)}", "driver": "Marine heatwave",
                 "region": region_label(c["lat"], c["lon"]), "reasons": reasons, "species": species,
                 "data_sources": [SOURCES_OBS, SOURCES_FC, "OBIS (species records)"] if species else [SOURCES_OBS, SOURCES_FC],
                 "classification": "DERIVED METRIC: simplified Hobday-style definition, 12-year baseline; not an official classification",
                 "recommendation": "Monitoring priority: review SST evolution and the species with records in this area.",
                 "evidence": ev,
                 "evidence_summary": [
                     {"label": "Maximum anomaly", "value": f"{ev['max_anomaly_c']:+.1f} °C"},
                     {"label": "Current anomaly", "value": f"{ev['current_anomaly_c']:+.1f} °C"},
                     {"label": "Duration", "value": f"{ev['duration_days']} days (since {ev['start_date']})"},
                     {"label": "Affected area", "value": f"{ev['area_km2']:,.0f} km²"},
                     {"label": "Cumulative intensity", "value": f"{ev.get('cumulative_intensity_c_days', 0):.0f} °C·days"},
                     {"label": "Biodiversity overlap", "value": f"{len(species)} species with records"},
                     {"label": "Conservation-sensitive species", "value": str(len(sensitive))},
                 ]})

    # 2. current anomalies and 3. forecast heat
    for h in monitor_service.hotspots(0, 2.0, 5, None)["items"]:
        add("SST_ANOMALY", SEV_BY_NAME[h["severity"]], h["lat"], h["lon"], _ts(day),
            f"SST anomaly {h['mean_anomaly']:+.1f} degC ({h['severity']}) in a 2x2 degree area near {abs(h['lat']):.1f}N, {abs(h['lon']):.1f}W",
            {"key": f"anom:{day}:{h['lat']}:{h['lon']}", "driver": "SST anomaly", "region": region_label(h["lat"], h["lon"]),
             "reasons": [f"Observed SST {h['value_c']:.1f} degC versus an average of {h['baseline_c']:.1f} degC for this date.",
                         f"Block-mean anomaly {h['mean_anomaly']:+.1f} degC, strongest cell {h['max_anomaly']:+.1f} degC.",
                         (f"Part of an ongoing heat run (median {h['persistence_days']} days)." if h.get("persistence_days") else "No sustained marine-heatwave run detected here.")],
             "data_sources": [SOURCES_OBS], "classification": "DERIVED METRIC from observations",
             "recommendation": "Monitoring priority; compare with neighbouring days on the Anomalies page.", "evidence": h,
             "evidence_summary": [
                 {"label": "Anomaly (2x2° block mean)", "value": f"{h['mean_anomaly']:+.2f} °C"},
                 {"label": "Strongest cell", "value": f"{h['max_anomaly']:+.2f} °C"},
                 {"label": "Observed SST / normal", "value": f"{h['value_c']:.1f} / {h['baseline_c']:.1f} °C"},
                 {"label": "Persistence", "value": f"{h['persistence_days']} days" if h.get("persistence_days") else "no sustained run"}]},
            related_anomaly_id=_nearest_anomaly(db, h["lat"], h["lon"], day))
    last_target = latest["target_dates"][-1]
    for h in monitor_service.hotspots(7, 2.0, 5, None)["items"]:
        if h["direction"] != "warm":
            continue
        add("SST_FORECAST_HEAT", SEV_BY_NAME[h["severity"]], h["lat"], h["lon"], _ts(last_target),
            f"Forecast SST anomaly {h['mean_anomaly']:+.1f} degC on {last_target} near {abs(h['lat']):.1f}N, {abs(h['lon']):.1f}W (model output)",
            {"key": f"fch:{last_target}:{h['lat']}:{h['lon']}", "driver": "Forecast heat", "region": region_label(h["lat"], h["lon"]),
             "reasons": [f"The ConvLSTM forecasts {h['value_c']:.1f} degC versus an average of {h['baseline_c']:.1f} degC on {last_target}.",
                         "This is a forecast with typical errors of a few tenths of a degC, not an observation."],
             "data_sources": [SOURCES_FC], "classification": "MODEL OUTPUT", "recommendation": "Check again when new observations arrive.",
             "evidence": h,
             "evidence_summary": [
                 {"label": "Forecast anomaly (day 7)", "value": f"{h['mean_anomaly']:+.2f} °C"},
                 {"label": "Forecast SST / normal", "value": f"{h['value_c']:.1f} / {h['baseline_c']:.1f} °C"},
                 {"label": "Forecast date", "value": last_target}]},
            related_forecast_id=_nearest_forecast(db, h["lat"], h["lon"], last_target))

    # 4. species exposure
    for sp in db.execute(select(Species).where(Species.watchlist.is_(True))).scalars():
        a = risk_service.species_assessment(db, e, sp.aphia_id, sp.scientific_name)
        if not a.get("available") or a["n_records"] < 20 or a["level"] not in ("HIGH", "CRITICAL"):
            continue
        rows = db.execute(select(func.avg(BiodiversityObservation.latitude), func.avg(BiodiversityObservation.longitude)).where(
            BiodiversityObservation.species_aphia_id == sp.aphia_id)).one()
        lat, lon = float(rows[0]), float(rows[1])
        risk_id = db.execute(select(EcologicalRiskScore.id).join(BiodiversityObservation,
                             EcologicalRiskScore.biodiversity_observation_id == BiodiversityObservation.id)
                             .where(BiodiversityObservation.species_aphia_id == sp.aphia_id).limit(1)).scalar_one_or_none()
        name = sp.common_name or sp.scientific_name
        add("ECOLOGICAL_RISK", SEV_BY_NAME[a["level"]], lat, lon, _ts(day),
            f"Potential environmental exposure {a['level']} for {name} ({sp.scientific_name}) based on {a['n_records']} recent OBIS records",
            {"key": f"species:{sp.aphia_id}:{day}", "driver": "Species environmental exposure", "region": "NE Pacific study region (recorded positions)",
             "reasons": a["reasons"], "species": [{"aphia_id": sp.aphia_id, "scientific_name": sp.scientific_name, "common_name": sp.common_name}],
             "data_sources": ["OBIS (species records)", SOURCES_OBS, SOURCES_FC],
             "classification": "DERIVED METRIC: project environmental risk indicator (potential exposure, not evidence of harm)",
             "recommendation": "Monitoring priority only; this is not a conservation assessment.", "evidence": {k: a[k] for k in ("score", "factors")},
             "evidence_summary": [
                 {"label": "Exposure score", "value": f"{a['score']:.2f} ({a['level']})"},
                 {"label": "Recent records used", "value": f"{a['n_records']} in {a['n_cells']} grid cells"},
                 {"label": "Records now ≥ 1 °C from normal", "value": f"{a['exposed_share'] * 100:.0f}%"},
                 {"label": "Conservation status", "value": (sp.iucn_category or "not confirmed")}]},
            related_risk_id=risk_id)
    db.commit()
    created["REFRESHED"] = refreshed["count"]
    return created


def publish(db: Session, user_id: uuid.UUID, days: int = 14) -> dict:
    e = load_env()
    if e.hist is None:
        raise RuntimeError("point_history.npz missing; run `python -m oceanmind_model export-dashboard` first")
    result = _publish_environment(db, e, user_id, days)
    result.pop("dataset_id", None)
    result.update(_publish_risk(db, e))
    result["alerts_created"] = generate_alerts(db, e)
    return result
