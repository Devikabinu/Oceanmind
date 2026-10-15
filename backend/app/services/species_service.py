"""Species catalogue + observations. Observations are real OBIS records stored by the sync job; taxonomy, common names
and conservation category are fetched from OBIS / WoRMS (see services/obis_client.py). Nothing is invented here."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.biodiversity_observation import BiodiversityObservation
from app.models.species import Species
from app.services import obis_client
from app.services.taxonomy import CONSERVATION_SENSITIVE, IUCN_LABELS, classify_group


class SpeciesNotFoundOnObis(Exception):
    pass


def upsert_species(db: Session, aphia_id: int, watchlist: bool | None = None) -> Species:
    """Create/refresh a catalogue entry from OBIS (+WoRMS vernacular, +OBIS red-list checklist)."""
    t = obis_client.taxon(aphia_id)
    if t is None or t.get("taxonRank") not in ("Species", None):
        raise SpeciesNotFoundOnObis(f"OBIS has no species-rank taxon with AphiaID {aphia_id}")
    name = t["scientificName"]
    names = obis_client.english_vernaculars(aphia_id)
    gbif_name = obis_client.gbif_common_name(name)
    gbif = obis_client.gbif_iucn(name)
    obis_category = obis_client.redlist_category(name)
    # Prefer GBIF (covers every IUCN category incl. Least Concern); fall back to the OBIS threatened-species checklist.
    category = gbif["code"] if gbif else obis_category
    row = db.execute(select(Species).where(Species.aphia_id == aphia_id)).scalar_one_or_none()
    if row is None:
        row = Species(aphia_id=aphia_id, scientific_name=name, taxon_group="Other marine organisms", sources={})
        db.add(row)
    row.scientific_name = name
    row.common_name = gbif_name or (names[0] if names else row.common_name)
    row.taxon_group = classify_group(t)
    row.class_name, row.order_name, row.family = t.get("class"), t.get("order"), t.get("family")
    row.iucn_category = category
    if gbif:
        row.iucn_source = "IUCN Red List category via GBIF" + (f" (IUCN taxon {gbif['iucn_taxon_id']})" if gbif.get("iucn_taxon_id") else "")
    elif obis_category:
        row.iucn_source = "IUCN Red List via OBIS red-list checklist (threatened species only)"
    else:
        row.iucn_source = None
    row.sources = {
        "taxonomy": f"https://obis.org/taxon/{aphia_id}",
        "worms": f"https://www.marinespecies.org/aphia.php?p=taxdetails&id={aphia_id}",
        "common_name": ("GBIF vernacular names (most frequent English name)" if gbif_name
                        else "WoRMS vernacular names (English)" if names else None),
        "conservation": (f"https://www.iucnredlist.org/species/{gbif['iucn_taxon_id']}" if gbif and gbif.get("iucn_taxon_id")
                         else "https://api.obis.org/v3/checklist/redlist"),
        # when the two sources disagree (e.g. one predates a reassessment) keep both visible instead of hiding it
        "conservation_alt": ({"source": "OBIS red-list checklist", "category": obis_category}
                             if gbif and obis_category and obis_category != gbif["code"] else None),
    }
    if watchlist is not None:
        row.watchlist = watchlist
    row.last_synced_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return row


def _obs_counts(db: Session):
    return (
        select(BiodiversityObservation.species_aphia_id.label("aid"), func.count().label("n"),
               func.max(BiodiversityObservation.timestamp).label("last"))
        .where(BiodiversityObservation.species_aphia_id.is_not(None))
        .group_by(BiodiversityObservation.species_aphia_id)
        .subquery()
    )


def species_dict(row: Species, n_obs: int | None = None, last_obs: datetime | None = None) -> dict:
    return {
        "aphia_id": row.aphia_id, "scientific_name": row.scientific_name, "common_name": row.common_name,
        "taxon_group": row.taxon_group, "class_name": row.class_name, "order_name": row.order_name, "family": row.family,
        "iucn_category": row.iucn_category, "iucn_label": IUCN_LABELS.get(row.iucn_category or ""),
        "iucn_source": row.iucn_source, "watchlist": row.watchlist,
        "n_observations": n_obs or 0, "last_observation": last_obs,
    }


def list_species(db: Session, q: str | None, group: str | None, threatened: bool, page: int, page_size: int,
                 status: str | None = None):
    counts = _obs_counts(db)
    stmt = select(Species, counts.c.n, counts.c.last).outerjoin(counts, counts.c.aid == Species.aphia_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Species.scientific_name.ilike(like), Species.common_name.ilike(like), Species.family.ilike(like),
                              Species.class_name.ilike(like), Species.order_name.ilike(like)))
    if group:
        stmt = stmt.where(Species.taxon_group == group)
    if threatened:
        stmt = stmt.where(Species.iucn_category.in_(CONSERVATION_SENSITIVE))
    if status == "UNCONFIRMED":
        stmt = stmt.where(Species.iucn_category.is_(None))
    elif status:
        stmt = stmt.where(Species.iucn_category == status)
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    rows = db.execute(
        stmt.order_by(func.coalesce(counts.c.n, 0).desc(), Species.scientific_name).offset((page - 1) * page_size).limit(page_size)
    ).all()
    groups = db.execute(select(Species.taxon_group, func.count()).group_by(Species.taxon_group)).all()
    status_col = func.coalesce(Species.iucn_category, "UNCONFIRMED")
    statuses = db.execute(select(status_col, func.count()).group_by(status_col)).all()
    return [species_dict(r, n, last) for r, n, last in rows], total, {g: n for g, n in groups}, {k: n for k, n in statuses}


def summary(db: Session) -> dict:
    """Headline biodiversity numbers for the dashboard."""
    n_species = db.execute(select(func.count()).select_from(Species)).scalar_one()
    n_rec, latest, first = db.execute(select(func.count(), func.max(BiodiversityObservation.timestamp),
                                             func.min(BiodiversityObservation.timestamp))
                                      .select_from(BiodiversityObservation)).one()
    recent = 0
    if latest is not None:
        recent = db.execute(select(func.count()).select_from(BiodiversityObservation)
                            .where(BiodiversityObservation.timestamp >= latest - timedelta(days=90))).scalar_one()
    with_records = db.execute(select(func.count(func.distinct(BiodiversityObservation.species_aphia_id)))
                              .where(BiodiversityObservation.species_aphia_id.is_not(None))).scalar_one()
    sensitive = db.execute(
        select(func.count(func.distinct(Species.aphia_id))).join(BiodiversityObservation, BiodiversityObservation.species_aphia_id == Species.aphia_id)
        .where(Species.iucn_category.in_(CONSERVATION_SENSITIVE))).scalar_one()
    return {"n_species": n_species, "species_with_records": with_records, "n_records": n_rec, "records_last_90_days": recent,
            "first_observation": first, "latest_observation": latest, "conservation_sensitive_with_records": sensitive,
            "note": "Records are a time-spread OBIS sample for the study region. Conservation-sensitive = IUCN VU, EN or CR as reported by the source."}


def get_species(db: Session, aphia_id: int) -> Species | None:
    return db.execute(select(Species).where(Species.aphia_id == aphia_id)).scalar_one_or_none()


def species_summary(db: Session, row: Species) -> dict:
    n, last, first = db.execute(
        select(func.count(), func.max(BiodiversityObservation.timestamp), func.min(BiodiversityObservation.timestamp))
        .where(or_(BiodiversityObservation.species_aphia_id == row.aphia_id,
                   BiodiversityObservation.species_name == row.scientific_name,
                   BiodiversityObservation.scientific_name == row.scientific_name))
    ).one()
    d = species_dict(row, n, last)
    d["first_observation"] = first
    d["sources"] = row.sources
    d["last_synced_at"] = row.last_synced_at
    return d


def observations(db: Session, row: Species, page: int, page_size: int, bbox: tuple | None):
    cond = or_(BiodiversityObservation.species_aphia_id == row.aphia_id,
               BiodiversityObservation.species_name == row.scientific_name,
               BiodiversityObservation.scientific_name == row.scientific_name)
    stmt = select(BiodiversityObservation).where(cond)
    if bbox:
        la0, la1, lo0, lo1 = bbox
        stmt = stmt.where(BiodiversityObservation.latitude.between(la0, la1),
                          BiodiversityObservation.longitude.between(lo0, lo1))
    total = db.execute(select(func.count()).select_from(stmt.order_by(None).subquery())).scalar_one()
    items = db.execute(stmt.order_by(BiodiversityObservation.timestamp.desc(), BiodiversityObservation.id)
                       .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return items, total


def species_in_bbox(db: Session, bbox: dict, days: int = 730, limit: int = 20) -> list[dict]:
    """Species with stored OBIS records inside a lat/lon box (e.g. a marine heatwave's bounding box)."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    key = func.coalesce(BiodiversityObservation.species_aphia_id, -1)
    rows = db.execute(
        select(key, func.min(BiodiversityObservation.species_name), func.count())
        .where(BiodiversityObservation.timestamp >= since,
               BiodiversityObservation.latitude.between(bbox["lat_min"], bbox["lat_max"]),
               BiodiversityObservation.longitude.between(bbox["lon_min"], bbox["lon_max"]))
        .group_by(key).order_by(func.count().desc()).limit(limit)
    ).all()
    catalogue = {s.aphia_id: s for s in db.execute(select(Species).where(Species.aphia_id.in_([r[0] for r in rows if r[0] > 0]))).scalars()}
    out = []
    for aid, name, n in rows:
        s = catalogue.get(aid)
        out.append({"aphia_id": aid if aid > 0 else None, "scientific_name": s.scientific_name if s else name,
                    "common_name": s.common_name if s else None, "taxon_group": s.taxon_group if s else None,
                    "iucn_category": s.iucn_category if s else None, "n_records": n})
    return out
