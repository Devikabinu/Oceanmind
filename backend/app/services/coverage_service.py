"""Which data exists where. Combines static facts about the public sources with what this installation has actually
loaded (database counts + the ML export), so the UI never implies global coverage that does not exist."""
from __future__ import annotations

import json

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


def _pacific_description() -> dict | None:
    try:
        from app.services import environment_store as es
        return es.get_store("pacific").describe()
    except Exception:  # noqa: BLE001 - the catalogue still lists the sources when the Pacific dataset is not built
        return None


def _climate_entries() -> list[dict]:
    from app.services import climate_indices as ci
    f = ci.index_file()
    d = json.loads(f.read_text()) if f.exists() else None
    out = []
    for key, name, provider, doc, desc, url in (
        ("oni", "Oceanic Niño Index (ONI)", "NOAA Climate Prediction Center", "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/ensostuff/ONI_v5.php",
         "3-month running mean of Niño-3.4 SST anomalies; +/-0.5 degC marks El Niño / La Niña conditions", ci.ONI_URL),
        ("pdo", "Pacific Decadal Oscillation (PDO) index", "NOAA National Centers for Environmental Information (ERSSTv5)", "https://www.ncei.noaa.gov/access/monitoring/pdo/",
         "Monthly index of the leading pattern of North Pacific SST variability", ci.PDO_URL),
    ):
        loaded = d is not None
        out.append({
            "id": key, "name": name, "provider": provider, "data_type": "Climate index (observed, derived by the provider)", "variables": [desc],
            "coverage_source": "Basin-wide index (one value per month)", "temporal_source": "Monthly values from the 19th century / 1950 to the latest published month; updated monthly",
            "resolution": "One value per month", "spatial_loaded": "Pacific-wide index" if loaded else "Nothing loaded",
            "latest_date": d[key]["latest_month"] if loaded else None, "status_kind": "loaded" if loaded else "integrated",
            "status_label": "Loaded" if loaded else "Integrated, not loaded: run `python -m app.jobs sync-climate-indices`",
            "records_label": f"{len(d[key]['series']):,} monthly values" if loaded else "0",
            "loaded_in_project": ("Used only as labelled context in anomaly explanations; it is never presented as the cause of an anomaly" if loaded else None),
            "database": {"registered": False}, "documentation": doc, "stored_rows": None, "url": url, "update_frequency": "Monthly",
            "last_updated": d[key]["retrieved_at"] if loaded else None, "processing": "Parsed as published; missing months are dropped, never filled.",
            "limitations": ["A basin-wide index does not by itself explain an anomaly at one place.", "The latest value can lag by several weeks."],
        })
    return out


def sources(db: Session) -> dict:
    """Per-source catalogue for the Ocean Data page."""
    try:
        e = load_env()
        export = {"start": "2012-01-01", "end": e.info["latest"]["observed_date"], "bounds": e.bounds}
    except OutputsUnavailable:
        export = None
    noaa, obis = (_ds_stats(db, n) for n in ("NOAA OISST v2.1", "OBIS"))
    n_species = db.execute(select(func.count()).select_from(Species)).scalar_one()
    n_obs_db = db.execute(select(func.count()).select_from(OceanObservation)).scalar_one()
    n_bio_db = db.execute(select(func.count()).select_from(BiodiversityObservation)).scalar_one()
    latest_bio = db.execute(select(func.max(BiodiversityObservation.timestamp))).scalar_one()
    obs_date = export["end"] if export else None
    pac = _pacific_description()
    pac_src = ((pac or {}).get("provider") or {}).get("source") or {}
    items = [
        {"id": "noaa", "name": "NOAA OISST v2.1", "provider": "NOAA National Centers for Environmental Information (NCEI), via NOAA CoastWatch ERDDAP", "data_type": "Gridded satellite + in-situ analysis (observed)",
         "variables": ["Sea surface temperature", "SST anomaly", "Estimation error", "Sea-ice concentration"],
         "coverage_source": "Global ocean, 0.25 degree grid", "temporal_source": "Daily, 1981-09 to near-real-time (recent values are preliminary and later revised)",
         "resolution": "0.25° x 0.25°, daily",
         "spatial_loaded": (("Pacific Ocean (60°S-65°N, 100°E-70°W) at 1°" + ("; NE Pacific study region at 0.25°" if export else "")) if pac else "NE Pacific study region (20-50°N, 160-120°W)" if export else "Nothing loaded"),
         "latest_date": (pac or {}).get("latest_date") or obs_date, "status_kind": "loaded" if (export or pac) else "not_loaded",
         "status_label": "Loaded (Pacific Ocean)" if pac else "Loaded (study region)" if export else "Not loaded",
         "records_label": f"{n_obs_db:,} stored rows (a 1° subset of the last 14 days); full 0.25° grid in the processed files" if export else "0",
         "loaded_in_project": (f"Pacific Ocean at 1°, {pac['first_date']} to {pac['latest_date']}; " if pac else "") + ("" if export is None else f"NE Pacific study region (20-50N, 160-120W) at 0.25°, {export['start']} to {export['end']}") or None,
         "database": noaa, "documentation": "https://www.ncei.noaa.gov/products/optimum-interpolation-sst",
         "stored_rows": n_obs_db,
         "url": (pac_src.get("urls") or ["https://psl.noaa.gov/data/gridded/data.noaa.oisst.v2.highres.html"])[0],
         "update_frequency": "Daily: the final product is about two weeks behind, the preliminary product about two days",
         "baseline": (pac or {}).get("baseline"), "last_updated": (pac or {}).get("source_timestamp") or (pac or {}).get("processed_at"),
         "freshness": (pac or {}).get("freshness"),
         "processing": ((pac or {}).get("processing") or "Regridded to the analysis grid, quality-checked, land-masked; anomaly = SST minus the daily climatology."),
         "limitations": ((pac or {}).get("limitations") or ["Coastal and small-scale features are not resolved at this resolution."])},
        {"id": "obis", "name": "OBIS", "provider": "Ocean Biodiversity Information System", "data_type": "Species occurrence records (observed)",
         "variables": ["Scientific name", "Position", "Event date", "Depth range", "Occurrence status", "Taxonomy"],
         "coverage_source": "Global; coverage varies strongly by species, region and sampling effort",
         "temporal_source": "Varies by record (historical to near-real-time)", "resolution": "Point records (lat/lon, event date)",
         "spatial_loaded": "Pacific Ocean and NE Pacific study region (time-spread selection per species); global density can be viewed live per species" if n_bio_db else "Nothing loaded",
         "latest_date": latest_bio.date().isoformat() if latest_bio else None,
         "status_kind": "loaded" if n_bio_db else "integrated", "status_label": "Loaded" if n_bio_db else "Integrated, not loaded",
         "records_label": f"{n_bio_db:,} records · {n_species} species",
         "loaded_in_project": f"{n_bio_db} stored records for {n_species} catalogued species (a time-spread selection of records per species across the Pacific)" if n_bio_db else "No records loaded yet; run `python -m app.jobs sync-biodiversity`",
         "database": obis, "documentation": "https://obis.org/", "stored_rows": n_bio_db, "url": "https://api.obis.org/v3/occurrence",
         "update_frequency": "Continuous at the source; refreshed here by `python -m app.jobs sync-biodiversity --region pacific`",
         "last_updated": (obis.get("last_successful_ingestion") or None), "processing": "Records are validated (coordinates, dates, duplicates), then stored with their taxonomy and the species' IUCN category (GBIF, falling back to the OBIS red-list checklist).",
         "limitations": ["Records show where animals were observed, not their range; recording effort is uneven and absence of records is not absence of species.",
                         "Only the watch-list species are loaded, with a time-spread selection of records for each."]},
        {"id": "convlstm", "name": "Project ConvLSTM forecast", "provider": "This project", "data_type": "Model output (not observation)",
         "variables": ["Forecast SST, days 1-7"], "coverage_source": "NE Pacific study region and the Pacific Ocean", "temporal_source": "Issued from the last processed day",
         "resolution": "0.25° x 0.25° (study region) and 1° (Pacific), daily, 7-day horizon", "spatial_loaded": "NE Pacific study region and the Pacific Ocean",
         "latest_date": (pac or {}).get("latest_date") or obs_date, "status_kind": "loaded" if (export or pac) else "not_loaded", "status_label": "Loaded" if (export or pac) else "Not loaded",
         "records_label": "7 daily maps (files)", "loaded_in_project": None if export is None else f"Forecast issued from {export['end']}",
         "database": {"registered": False}, "documentation": None, "stored_rows": None, "url": None,
         "update_frequency": "Reissued whenever new observations are processed",
         "processing": "ConvLSTM trained on the NE Pacific (2012-2023); applied unchanged to the Pacific Ocean and compared with persistence on a held-out period.",
         "limitations": ["Skill outside the northeast Pacific is limited and is reported against a persistence forecast.", "A prediction, never an observation."]},
    ] + _climate_entries()
    return {"items": items}
