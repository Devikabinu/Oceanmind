"""Marine biodiversity: species catalogue (OBIS/WoRMS-backed), real OBIS observations, species-level exposure."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, require_roles
from app.api.query_validation import validate_filter_ranges
from app.models.enums import UserRole
from app.schemas.species import (
    PaginatedSpecies,
    SpeciesDetail,
    SpeciesObservations,
    SpeciesRead,
    SpeciesRiskRead,
    SpeciesSearchHit,
    TrackSpeciesRequest,
)
from app.schemas.biodiversity_observation import BiodiversityObservationRead
from app.services import obis_client, risk_service, species_service
from app.services.environment import OutputsUnavailable, env as load_env
from app.services.taxonomy import GROUPS, classify_group

router = APIRouter(prefix="/species", tags=["species"], dependencies=[Depends(get_current_user)])

_CAN_TRACK = require_roles(UserRole.ADMIN, UserRole.RESEARCHER)


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"External source unavailable: {exc}")


@router.get("", response_model=PaginatedSpecies)
def list_species(
    q: str | None = Query(None, min_length=1, max_length=100, description="Scientific or common name fragment"),
    group: str | None = Query(None, description="One of: " + ", ".join(GROUPS)),
    threatened: bool = Query(False, description="Only species whose source-reported IUCN category is VU, EN or CR"),
    status: str | None = Query(None, pattern="^(EX|EW|CR|EN|VU|NT|LC|DD|NE|UNCONFIRMED)$", description="IUCN category code, or UNCONFIRMED"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    db: Session = Depends(get_db),
) -> PaginatedSpecies:
    if group is not None and group not in GROUPS:
        raise HTTPException(status_code=422, detail=f"group must be one of {GROUPS}")
    items, total, groups, statuses = species_service.list_species(db, q, group, threatened, page, page_size, status)
    return PaginatedSpecies(items=items, total=total, page=page, page_size=page_size, groups=groups, statuses=statuses)


@router.get("/summary")
def biodiversity_summary(db: Session = Depends(get_db)) -> dict:
    return species_service.summary(db)


@router.get("/search", response_model=list[SpeciesSearchHit])
def search_obis(q: str = Query(..., min_length=3, max_length=80), db: Session = Depends(get_db)) -> list[SpeciesSearchHit]:
    """Live OBIS taxon search (any marine species, not only catalogued ones)."""
    try:
        hits = obis_client.taxon_complete(q)
    except obis_client.ExternalServiceError as exc:
        raise _unavailable(exc)
    known = {h["id"] for h in hits if species_service.get_species(db, h["id"]) is not None}
    return [SpeciesSearchHit(aphia_id=h["id"], scientific_name=h["scientificName"], rank=h.get("rank"),
                             taxon_group=classify_group(h), class_name=h.get("class"), family=h.get("family"),
                             in_catalogue=h["id"] in known) for h in hits]


@router.post("", response_model=SpeciesDetail, status_code=status.HTTP_201_CREATED, dependencies=[Depends(_CAN_TRACK)])
def track_species(payload: TrackSpeciesRequest, db: Session = Depends(get_db)) -> dict:
    """Add (or refresh) a species in the catalogue from OBIS/WoRMS. Observations are loaded by the sync job."""
    try:
        row = species_service.upsert_species(db, payload.aphia_id)
    except species_service.SpeciesNotFoundOnObis as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except obis_client.ExternalServiceError as exc:
        raise _unavailable(exc)
    return species_service.species_summary(db, row)


def _get(db: Session, aphia_id: int):
    row = species_service.get_species(db, aphia_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Species not in the catalogue")
    return row


@router.get("/{aphia_id}", response_model=SpeciesDetail)
def get_species(aphia_id: int, db: Session = Depends(get_db)) -> dict:
    return species_service.species_summary(db, _get(db, aphia_id))


@router.get("/{aphia_id}/observations", response_model=SpeciesObservations)
def species_observations(
    aphia_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    min_latitude: float | None = Query(None, ge=-90, le=90),
    max_latitude: float | None = Query(None, ge=-90, le=90),
    min_longitude: float | None = Query(None, ge=-180, le=180),
    max_longitude: float | None = Query(None, ge=-180, le=180),
    db: Session = Depends(get_db),
) -> SpeciesObservations:
    validate_filter_ranges(None, None, min_latitude, max_latitude, min_longitude, max_longitude)
    row = _get(db, aphia_id)
    bbox = None
    if None not in (min_latitude, max_latitude, min_longitude, max_longitude):
        bbox = (min_latitude, max_latitude, min_longitude, max_longitude)
    items, total = species_service.observations(db, row, page, page_size, bbox)
    return SpeciesObservations(items=[BiodiversityObservationRead.model_validate(i) for i in items],
                               total=total, page=page, page_size=page_size)


@router.get("/{aphia_id}/risk", response_model=SpeciesRiskRead)
def species_risk(aphia_id: int, dataset: str | None = None, db: Session = Depends(get_db)) -> dict:
    """Potential environmental exposure of the species' recent records. `dataset` (e.g. pacific) selects the environmental inputs; omitted = NE Pacific."""
    row = _get(db, aphia_id)
    try:
        if dataset not in (None, risk_service.LEGACY_DATASET):
            from app.api.v1.environment import guard
            inp = guard(risk_service.inputs_for, dataset, None)
            out = risk_service.species_assessment(db, inp, row.aphia_id, row.scientific_name)
            gen = inp.source.get("is_observational") is False
            out["labels"] = {"records": "OBSERVATION (OBIS)", "conditions": f"{inp.source.get('provider_id', dataset)} ({'dataset provider; not a satellite-observation record' if gen else 'observational'})",
                             "score": "DERIVED METRIC (project environmental risk indicator; potential exposure, not proof of harm)"}
            return out
        return risk_service.species_assessment(db, load_env(), row.aphia_id, row.scientific_name)
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/{aphia_id}/distribution")
def species_distribution(aphia_id: int, precision: int = Query(3, ge=2, le=4), db: Session = Depends(get_db)) -> dict:
    """Global gridded OBIS record counts for the species (GeoJSON), fetched live from OBIS."""
    row = _get(db, aphia_id)
    try:
        grid = obis_client.occurrence_grid(row.scientific_name, precision)
    except obis_client.ExternalServiceError as exc:
        raise _unavailable(exc)
    return {"source": "OBIS occurrence grid (live)", "scientific_name": row.scientific_name, "precision": precision,
            "geojson": grid, "note": "Counts of OBIS records per grid cell. Sampling effort is uneven, so this is not a range map."}
