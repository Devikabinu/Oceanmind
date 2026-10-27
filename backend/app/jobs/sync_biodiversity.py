"""Fill the species catalogue and biodiversity observations from OBIS / WoRMS (real records, nothing synthesised).

For each species: resolve the AphiaID, store taxonomy + common name + red-list category, then fetch a time-spread
sample of recent OBIS records inside the study region (N windows x a few records) through the normal OBIS adapter
(same validation, quality report and dataset/job bookkeeping as an API-triggered ingestion).
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.base import IngestionParams, QualityMetrics
from app.ingestion.obis_adapter import OBISAdapter
from app.jobs.watchlist import WATCHLIST
from app.models.data_quality_report import DataQualityReport
from app.models.dataset import Dataset
from app.models.enums import IngestionJobStatus
from app.models.ingestion_job import IngestionJob
from app.models.biodiversity_observation import BiodiversityObservation
from app.models.species import Species
from app.repositories.data_source_repository import DataSourceRepository
from app.services import obis_client, species_service
from app.services.environment import OutputsUnavailable, env as load_env

logger = logging.getLogger("ocean_platform")


def _study_bounds() -> dict:
    try:
        return load_env().bounds
    except OutputsUnavailable:
        return {"lat_min": 20.0, "lat_max": 50.0, "lon_min": -160.0, "lon_max": -120.0}


def pacific_parts() -> list[dict]:
    """Pacific basin as two longitude windows (100E..180 and 180..70W) so the OBIS polygon never crosses the antimeridian."""
    return [dict(lat_min=-60.0, lat_max=65.0, lon_min=100.0, lon_max=180.0), dict(lat_min=-60.0, lat_max=65.0, lon_min=-180.0, lon_max=-70.0)]


def _windows(end: date, months: int, n: int) -> list[tuple[date, date]]:
    total_days = int(months * 30.44)
    step = total_days // n
    start = end - timedelta(days=total_days)
    return [(start + timedelta(days=k * step), start + timedelta(days=(k + 1) * step - 1)) for k in range(n)]


def resolve_aphia(name: str) -> int | None:
    for hit in obis_client.taxon_complete(name, limit=10):
        if hit["scientificName"].lower() == name.lower():
            return int(hit["id"])
    return None


def sync_species(db: Session, user_id: uuid.UUID, name: str, months: int = 24, windows: int = 8,
                 per_window: int = 120, today: date | None = None, force: bool = False, region: str = "ne_pacific") -> dict:
    today = today or datetime.now(timezone.utc).date()
    aphia = resolve_aphia(name)
    if aphia is None:
        return {"species": name, "status": "not_found_on_obis"}
    sp = species_service.upsert_species(db, aphia, watchlist=True)
    existing = db.execute(select(func.count()).select_from(BiodiversityObservation).where(
        BiodiversityObservation.species_aphia_id == aphia)).scalar_one()
    already_done = db.execute(select(func.count()).select_from(IngestionJob).where(
        IngestionJob.params["scientific_name"].as_string() == sp.scientific_name,
        IngestionJob.params["region"].as_string() == region,
        IngestionJob.status == IngestionJobStatus.COMPLETED)).scalar_one()
    if already_done and not force:
        return {"species": sp.scientific_name, "aphia_id": aphia, "status": "skipped_already_synced", "records_existing": existing, "previous_completed_syncs": already_done}
    parts = pacific_parts() if region == "pacific" else [_study_bounds()]
    b = {"lat_min": min(p["lat_min"] for p in parts), "lat_max": max(p["lat_max"] for p in parts),
         "lon_min": min(p["lon_min"] for p in parts), "lon_max": max(p["lon_max"] for p in parts)}
    adapter = OBISAdapter()
    source = DataSourceRepository(db).get_by_name(adapter.data_source_name)
    if source is None:
        raise RuntimeError("OBIS data source is not registered (start the API once to seed data sources)")
    spans = _windows(today, months, windows)
    dataset = Dataset(data_source_id=source.id, name=f"OBIS {sp.scientific_name} {spans[0][0]}_{spans[-1][1]} (selected records)",
                      kind=adapter.dataset_kind, temporal_start=datetime.combine(spans[0][0], datetime.min.time(), tzinfo=timezone.utc),
                      temporal_end=datetime.combine(spans[-1][1], datetime.min.time(), tzinfo=timezone.utc),
                      min_latitude=b["lat_min"], max_latitude=b["lat_max"], min_longitude=b["lon_min"], max_longitude=b["lon_max"],
                      record_count=0)
    db.add(dataset)
    db.flush()
    job = IngestionJob(data_source_id=source.id, dataset_id=dataset.id, created_by=user_id, status=IngestionJobStatus.RUNNING,
                       params={"scientific_name": sp.scientific_name, "region": region, "windows": windows, "max_records_per_window": per_window,
                               "start_date": spans[0][0].isoformat(), "end_date": spans[-1][1].isoformat(),
                               "min_latitude": b["lat_min"], "max_latitude": b["lat_max"],
                               "min_longitude": b["lon_min"], "max_longitude": b["lon_max"]},
                       started_at=datetime.now(timezone.utc))
    db.add(job)
    db.commit()
    total = QualityMetrics()
    loaded = 0
    t0 = time.perf_counter()
    try:
        for start, end in spans:
            for part in parts:
                p = IngestionParams(start_date=start, end_date=end, min_latitude=part["lat_min"], max_latitude=part["lat_max"],
                                    min_longitude=part["lon_min"], max_longitude=part["lon_max"],
                                    scientific_name=sp.scientific_name, max_records=per_window)
                m, n = adapter.run(p, dataset.id, db)
                loaded += n
                for f in ("records_read", "records_valid", "records_rejected", "missing_values", "duplicate_records",
                          "invalid_coordinates", "invalid_timestamps", "outliers", "schema_mismatches"):
                    setattr(total, f, getattr(total, f) + getattr(m, f))
        job.status = IngestionJobStatus.COMPLETED
    except Exception as exc:  # noqa: BLE001 - recorded on the job
        logger.exception("OBIS sync failed for %s", name)
        db.rollback()
        job = db.get(IngestionJob, job.id)
        job.status = IngestionJobStatus.FAILED
        job.error_message = str(exc)[:1000]
    dataset = db.get(Dataset, dataset.id)
    dataset.record_count = loaded
    job.records_read, job.records_valid, job.records_rejected = total.records_read, total.records_valid, total.records_rejected
    job.completed_at = datetime.now(timezone.utc)
    job.execution_time_seconds = time.perf_counter() - t0
    db.add(DataQualityReport(dataset_id=dataset.id, ingestion_job_id=job.id, records_read=total.records_read,
                             records_valid=total.records_valid, records_rejected=total.records_rejected,
                             missing_values=total.missing_values, duplicate_records=total.duplicate_records,
                             invalid_coordinates=total.invalid_coordinates, invalid_timestamps=total.invalid_timestamps,
                             invalid_sst=0, outliers=total.outliers, schema_mismatches=total.schema_mismatches,
                             details={"selection": f"{windows} time windows x up to {per_window} OBIS records per area, {region} study area"}))
    db.commit()
    return {"species": sp.scientific_name, "aphia_id": aphia, "status": job.status.value, "records_loaded": loaded,
            "iucn": sp.iucn_category}


def run(db: Session, user_id: uuid.UUID, names: list[str] | None = None, **kw) -> list[dict]:
    out = []
    for name in names or WATCHLIST:
        try:
            res = sync_species(db, user_id, name, **kw)
        except Exception as exc:  # noqa: BLE001 - keep going; report per species
            db.rollback()
            res = {"species": name, "status": "error", "error": str(exc)[:200]}
        logger.info("sync %s", res)
        print(res, flush=True)
        out.append(res)
    return out


def backfill_species_columns(db: Session) -> int:
    """Rows ingested before species columns existed: fill species_name/aphia where the catalogue knows the name."""
    n = 0
    for sp in db.execute(select(Species)).scalars():
        rows = db.execute(select(BiodiversityObservation).where(
            BiodiversityObservation.species_aphia_id.is_(None),
            BiodiversityObservation.scientific_name.like(f"{sp.scientific_name}%"))).scalars().all()
        for r in rows:
            r.species_name, r.species_aphia_id = sp.scientific_name, sp.aphia_id
            n += 1
    db.commit()
    return n
