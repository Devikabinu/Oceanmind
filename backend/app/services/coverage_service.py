"""Which data exists where. Combines static facts about the public sources with what this installation has actually
loaded (database counts + the ML export), so the UI never implies global coverage that does not exist."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.biodiversity_observation import BiodiversityObservation
from app.models.data_source import DataSource
from app.models.dataset import Dataset
from app.models.ingestion_job import IngestionJob
from app.models.enums import IngestionJobStatus
from app.models.ocean_observation import OceanObservation
from app.models.species import Species
from app.services.environment import OutputsUnavailable, env as load_env

# Approximate ocean-basin boxes for navigation only: (south, west, north, east); east may exceed 180 for the Pacific.
BASINS = [
    ("north_pacific", "North Pacific", (0, 120, 60, 250)),
    ("south_pacific", "South Pacific", (-60, 150, 0, 290)),
    ("north_atlantic", "North Atlantic", (0, -80, 65, 0)),
    ("south_atlantic", "South Atlantic", (-60, -70, 0, 20)),
    ("indian", "Indian Ocean", (-60, 20, 30, 120)),
    ("arctic", "Arctic Ocean", (66, -180, 90, 180)),
    ("southern", "Southern Ocean", (-90, -180, -60, 180)),
]


def _norm(lon: float) -> float:
    return lon % 360


def _overlap(box: tuple, study: dict) -> bool:
    s, w, n, e = box
    if study["lat_max"] < s or study["lat_min"] > n:
        return False
    sw, se = _norm(study["lon_min"]), _norm(study["lon_max"])
    bw, be = _norm(w), (e if e > 180 else _norm(e))
    if e - w >= 360:
        return True
    return not (se < bw or sw > be) if bw <= be else (sw >= bw or se <= be)


def regions(db: Session | None = None) -> dict:
    try:
        e = load_env()
        study = e.bounds
        latest = e.info["latest"]["observed_date"]
    except OutputsUnavailable:
        study, latest = None, None
    out = []
    for rid, name, box in BASINS:
        covered = bool(study) and _overlap(box, study)
        n_rec = None
        if db is not None:
            s, w, n, east = box
            q = select(func.count()).select_from(BiodiversityObservation).where(BiodiversityObservation.latitude.between(s, n))
            lo_w, lo_e = ((w + 180) % 360 - 180, (east + 180) % 360 - 180)
            if east - w >= 360:
                pass
            elif lo_w <= lo_e:
                q = q.where(BiodiversityObservation.longitude.between(lo_w, lo_e))
            else:
                q = q.where((BiodiversityObservation.longitude >= lo_w) | (BiodiversityObservation.longitude <= lo_e))
            n_rec = db.execute(q).scalar_one()
        out.append({
            "id": rid, "name": name, "approx_bounds": [[box[0], box[1]], [box[2], box[3]]],
            "project_data": "partial" if covered else "none",
            "note": ("The detailed study region lies inside this basin; SST, forecast, heatwave and risk layers cover only that part."
                     if covered else "No SST, forecast or risk data are loaded for this basin. OBIS species distributions can still be viewed."),
            "stored_species_records": n_rec,
        })
    return {"study_region": None if study is None else {"name": "NE Pacific study region", **study, "latest_observed_date": latest},
            "regions": out}


def _ds_stats(db: Session, source_name: str) -> dict:
    src = db.execute(select(DataSource).where(DataSource.name == source_name)).scalar_one_or_none()
    if src is None:
        return {"registered": False}
    n, rec, t0, t1 = db.execute(
        select(func.count(), func.coalesce(func.sum(Dataset.record_count), 0), func.min(Dataset.temporal_start), func.max(Dataset.temporal_end))
        .where(Dataset.data_source_id == src.id)
    ).one()
    last_ok = db.execute(
        select(func.max(IngestionJob.completed_at)).where(IngestionJob.data_source_id == src.id,
                                                          IngestionJob.status == IngestionJobStatus.COMPLETED)
    ).scalar_one()
    return {"registered": True, "status": src.status.value, "url": src.source_url, "datasets": n, "records": int(rec),
            "temporal_start": t0, "temporal_end": t1, "last_successful_ingestion": last_ok}


def sources(db: Session) -> dict:
    """Per-source catalogue for the Ocean Data page."""
    try:
        e = load_env()
        export = {"start": "2012-01-01", "end": e.info["latest"]["observed_date"], "bounds": e.bounds}
    except OutputsUnavailable:
        export = None
    noaa, cop, obis = (_ds_stats(db, n) for n in ("NOAA OISST v2.1", "Copernicus Marine SST", "OBIS"))
    n_species = db.execute(select(func.count()).select_from(Species)).scalar_one()
    n_obs_db = db.execute(select(func.count()).select_from(OceanObservation)).scalar_one()
    n_bio_db = db.execute(select(func.count()).select_from(BiodiversityObservation)).scalar_one()
    latest_bio = db.execute(select(func.max(BiodiversityObservation.timestamp))).scalar_one()
    obs_date = export["end"] if export else None
    items = [
        {"id": "noaa", "name": "NOAA OISST v2.1", "provider": "NOAA Physical Sciences Laboratory", "data_type": "Gridded satellite + in-situ analysis (observed)",
         "variables": ["Sea surface temperature", "SST anomaly", "Estimation error", "Sea-ice concentration"],
         "coverage_source": "Global ocean, 0.25 degree grid", "temporal_source": "Daily, 1981-09 to near-real-time (recent values are preliminary and later revised)",
         "resolution": "0.25° x 0.25°, daily",
         "spatial_loaded": "NE Pacific study region (20-50°N, 160-120°W)" if export else "Nothing loaded",
         "latest_date": obs_date, "status_kind": "loaded" if export else "not_loaded",
         "status_label": "Loaded (study region)" if export else "Not loaded",
         "records_label": f"{n_obs_db:,} stored rows (1° sample of the last 14 days); full 0.25° grid in the processed files" if export else "0",
         "loaded_in_project": None if export is None else f"Study region (20-50N, 160-120W), {export['start']} to {export['end']}, used by the forecast, anomaly and heatwave features",
         "database": noaa, "documentation": "https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html",
         "stored_rows": n_obs_db},
        {"id": "copernicus", "name": "Copernicus Marine SST", "provider": "Copernicus Marine Service (CMEMS)", "data_type": "Multi-product SST ensemble (observed/analysis)",
         "variables": ["Sea surface temperature"], "coverage_source": "Global ocean (dataset-specific grid)",
         "temporal_source": "Near-real-time and reprocessed products (see dataset page)", "resolution": "Dataset-specific",
         "spatial_loaded": "Nothing loaded" if cop.get("records", 0) == 0 else "See datasets",
         "latest_date": None if cop.get("records", 0) == 0 else (cop.get("temporal_end").date().isoformat() if cop.get("temporal_end") else None),
         "status_kind": "integrated" if cop.get("records", 0) == 0 else "loaded",
         "status_label": "Integrated (adapter available), not loaded: needs credentials" if cop.get("records", 0) == 0 else "Loaded",
         "records_label": str(cop.get("records", 0)),
         "loaded_in_project": "Adapter is available; requires free Copernicus credentials to ingest" if cop.get("records", 0) == 0 else f"{cop['records']} records loaded",
         "database": cop, "documentation": "https://data.marine.copernicus.eu/", "stored_rows": cop.get("records", 0)},
        {"id": "obis", "name": "OBIS", "provider": "Ocean Biodiversity Information System", "data_type": "Species occurrence records (observed)",
         "variables": ["Scientific name", "Position", "Event date", "Depth range", "Occurrence status", "Taxonomy"],
         "coverage_source": "Global; coverage varies strongly by species, region and sampling effort",
         "temporal_source": "Varies by record (historical to near-real-time)", "resolution": "Point records (lat/lon, event date)",
         "spatial_loaded": "NE Pacific study region (sampled); global density can be viewed live per species" if n_bio_db else "Nothing loaded",
         "latest_date": latest_bio.date().isoformat() if latest_bio else None,
         "status_kind": "loaded" if n_bio_db else "integrated", "status_label": "Loaded (sample)" if n_bio_db else "Integrated, not loaded",
         "records_label": f"{n_bio_db:,} records · {n_species} species",
         "loaded_in_project": f"{n_bio_db} stored records for {n_species} catalogued species (a time-spread sample per species in the study region)" if n_bio_db else "No records loaded yet; run `python -m app.jobs sync-biodiversity`",
         "database": obis, "documentation": "https://obis.org/", "stored_rows": n_bio_db},
        {"id": "convlstm", "name": "Project ConvLSTM forecast", "provider": "This project", "data_type": "Model output (not observation)",
         "variables": ["Forecast SST, days 1-7"], "coverage_source": "Study region only", "temporal_source": "Issued from the last processed day",
         "resolution": "0.25° x 0.25°, daily, 7-day horizon", "spatial_loaded": "NE Pacific study region",
         "latest_date": obs_date, "status_kind": "loaded" if export else "not_loaded", "status_label": "Loaded" if export else "Not generated",
         "records_label": "7 daily maps (files)", "loaded_in_project": None if export is None else f"Forecast issued from {export['end']}",
         "database": {"registered": False}, "documentation": None, "stored_rows": None},
    ]
    return {"items": items}
