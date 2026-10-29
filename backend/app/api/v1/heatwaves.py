"""Marine heatwaves (project-level, simplified Hobday definition) from the precomputed heatwave results of a dataset.

`dataset` is optional everywhere: omitted means `ne_pacific`, the original behaviour. `region` is a region id from /api/environment/regions."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.environment import guard
from app.services import heatwave_service as svc
from app.services import species_service
from app.services.environment import OutputsUnavailable

router = APIRouter(prefix="/heatwaves", tags=["heatwaves"], dependencies=[Depends(get_current_user)])


def _guard(fn, *args, **kw):
    try:
        return guard(fn, *args, **kw)
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("")
def list_heatwaves(
    min_category: int = Query(1, ge=1, le=4, description="1=Moderate .. 4=Extreme (project scale)"),
    min_area_km2: float = Query(0, ge=0),
    dataset: str | None = Query(None, description="ne_pacific (default) or another dataset from /api/environment/datasets"),
    region: str | None = Query(None, description="Only events whose footprint intersects this region id"),
) -> dict:
    return _guard(svc.list_events, dataset, min_category, min_area_km2, region)


@router.get("/timeseries")
def heatwave_timeseries(days: int = Query(365, ge=7, le=6000), dataset: str | None = None) -> dict:
    return _guard(svc.timeseries, days, dataset)


@router.get("/map")
def heatwave_map(dataset: str | None = None, region: str | None = None, date: str | None = Query(None, description="YYYY-MM-DD; default the latest date")) -> dict:
    """Heatwave cells (anomaly) on a date, for the map. Null = not in a heatwave / land / no data."""
    return _guard(svc.map_layer_on, dataset, region, date)


@router.get("/history")
def heatwave_history(
    dataset: str | None = None, year: int | None = Query(None, ge=1980, le=2100), start: str | None = None, end: str | None = None,
    min_category: int = Query(1, ge=1, le=4), region: str | None = None, status: str | None = Query(None, pattern="^(ACTIVE|ENDED|active|ended)$"),
    sort: str = Query("start", pattern="^(start|duration|area|intensity)$"), limit: int = Query(100, ge=1, le=500),
) -> dict:
    """Historical marine-heatwave events of the whole record (active and ended): start, end, duration, peak, category; evolution via /history/{id}."""
    return _guard(svc.history_list, dataset, year, start, end, min_category, region, status, sort, limit)


@router.get("/on/{date}")
def heatwaves_on_date(date: str, dataset: str | None = None) -> dict:
    """Events in progress on a date (with the number of cells they cover that day)."""
    return {"date": date, "dataset": dataset, "items": _guard(svc.events_on, dataset, date)}


@router.get("/history/{event_id}")
def heatwave_history_event(event_id: str, dataset: str | None = None, date: str | None = Query(None, description="footprint date within the event; default its peak day"),
                           db: Session = Depends(get_db)) -> dict:
    result = _guard(svc.history_event, event_id, dataset, date)
    if result is None:
        raise HTTPException(status_code=404, detail="Historical heatwave event not found")
    from app.services import location_report, risk_service
    import numpy as np
    d = svc.data(dataset)
    inp = risk_service.inputs_for(d.dataset, d.info["latest_date"])             # the grid is the same on every date: only the cell lookup is needed here
    fp = result["footprint"]
    grid = np.zeros((len(d.lat), len(d.lon)), dtype=bool)
    for la, lo in zip(fp["lat"], fp["lon"]):
        c = inp.cell(la, lo)
        if c is not None:
            grid[c] = True
    species = location_report.species_in_mask(db, inp, grid, 20)
    result["species_in_area"] = species
    result["biodiversity_evidence"] = "observed" if species else "insufficient_coverage"
    result["species_note"] = (f"Species with stored OBIS records in the cells this event covered on {fp['date']} (last 2 years). Potential exposure only; records are not ranges."
                              + ("" if species else " No stored records fall in those cells: that is limited biodiversity coverage, not evidence that no animals were present."))
    return result


@router.get("/{event_id}")
def get_heatwave(event_id: str, dataset: str | None = None, db: Session = Depends(get_db)) -> dict:
    result = _guard(svc.get_event, event_id, dataset)
    if result is None:
        raise HTTPException(status_code=404, detail="Heatwave event not found (events are recomputed with each data export)")
    from app.services import location_report
    footprint_species = location_report.species_in_event_footprint(db, result["event"]["dataset"], event_id, 20) if result["event"]["dataset"] != svc.LEGACY_DATASET else None
    if footprint_species is not None:
        species = {(s["aphia_id"], s["scientific_name"]): s for s in footprint_species}
        area = "the cells of this event"
    else:
        species = {}
        for seg in svc.bbox_segments(result["event"]["bbox"]):
            for s in species_service.species_in_bbox(db, seg):
                k = (s["aphia_id"], s["scientific_name"])
                if k in species:
                    species[k]["n_records"] += s["n_records"]
                else:
                    species[k] = dict(s)
        area = "the event's bounding box"
    result["species_in_area"] = sorted(species.values(), key=lambda s: -s["n_records"])[:20]
    result["biodiversity_evidence"] = "observed" if species else "insufficient_coverage"
    result["species_note"] = (f"Species with stored OBIS records in {area} (last 2 years). Potential exposure only."
                              + ("" if species else f" No stored records fall in {area}: that is limited biodiversity coverage, not evidence that no animals are present."))
    from app.services import explain_service
    result["narrative"] = explain_service.explain_event(result["event"], svc.data(dataset).info, result["species_in_area"], result["biodiversity_evidence"])
    return result
