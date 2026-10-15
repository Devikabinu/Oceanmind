"""Marine heatwaves (project-level, simplified Hobday definition) from the ML pipeline export."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services import heatwave_service as svc
from app.services import species_service
from app.services.environment import OutputsUnavailable

router = APIRouter(prefix="/heatwaves", tags=["heatwaves"], dependencies=[Depends(get_current_user)])


def _guard(fn, *args):
    try:
        return fn(*args)
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("")
def list_heatwaves(
    min_category: int = Query(1, ge=1, le=4, description="1=Moderate .. 4=Extreme (project scale)"),
    min_area_km2: float = Query(0, ge=0),
) -> dict:
    return _guard(svc.list_events, min_category, min_area_km2)


@router.get("/timeseries")
def heatwave_timeseries(days: int = Query(365, ge=7, le=6000)) -> dict:
    return _guard(svc.timeseries, days)


@router.get("/{event_id}")
def get_heatwave(event_id: str, db: Session = Depends(get_db)) -> dict:
    result = _guard(svc.get_event, event_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Heatwave event not found (events are recomputed with each data export)")
    bbox = result["event"]["bbox"]
    result["species_in_area"] = species_service.species_in_bbox(db, bbox)
    result["species_note"] = "Species with stored OBIS records inside the event's bounding box (last 2 years). Potential exposure only."
    return result
