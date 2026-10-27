"""Dashboard endpoints backed by the ML pipeline's output files (no database tables of their own)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services import monitor_service as svc

router = APIRouter(prefix="/monitor", tags=["monitor"], dependencies=[Depends(get_current_user)])

LayerName = Literal["observed", "observed_anomaly", "forecast", "forecast_anomaly", "heatwave", "risk",
                    "hindcast", "hindcast_truth", "hindcast_error"]
_DATE = r"^\d{4}-\d{2}-\d{2}$"


def _guard(fn, *args):
    try:
        return fn(*args)
    except svc.OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    return _guard(svc.overview, db)


@router.get("/performance")
def performance() -> dict:
    return _guard(svc.performance)


@router.get("/map")
def map_layer(
    layer: LayerName = "forecast",
    horizon: int = Query(1, ge=1, le=svc.N_HORIZONS),
    date: str | None = Query(None, pattern=_DATE, description="Observed layers only: a date inside the stored 2-year history"),
    dataset: str | None = Query(None, description="Optional processed dataset (e.g. 'pacific'). Omitted: the legacy NE Pacific dashboard export, unchanged."),
    region: str | None = Query(None, description="With `dataset`: a named region id (see /api/environment/regions)"),
    max_cells: int = Query(20000, ge=100, le=200000),
    db: Session = Depends(get_db),
) -> dict:
    if dataset is not None or region is not None:
        if layer not in ("observed", "observed_anomaly"):
            raise HTTPException(status_code=422, detail="dataset/region apply to the observed and observed_anomaly layers only")
        from app.api.v1.environment import guard
        from app.services import environment_store as es
        out = guard(es.map_response, dataset, "sst" if layer == "observed" else "anomaly", date, region, None, max_cells)
        out.update(layer=layer, horizon=horizon, coverage_stats=out["coverage"], coverage=out["dataset"]["extent"])
        return out
    return _guard(svc.map_layer, layer, horizon, db, date)


@router.get("/location")
def location(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
             db: Session = Depends(get_db)) -> dict:
    """Everything known about one clicked location (or a clear 'outside coverage' answer)."""
    return _guard(svc.location, db, lat, lon)


@router.get("/history")
def history(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
            days: int = Query(365, ge=14, le=730)) -> dict:
    result = _guard(svc.history, lat, lon, days)
    if result is None:
        raise HTTPException(status_code=404, detail="No ocean data at this location (land or outside the study region)")
    return result


@router.get("/point")
def point(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)) -> dict:
    result = _guard(svc.point, lat, lon)
    if result is None:
        raise HTTPException(status_code=404, detail="No ocean data at this location (land or outside the study region)")
    return result


@router.get("/region")
def region(name: Literal["all", "north", "south", "west", "east"] = "all") -> dict:
    return _guard(svc.region, name)


@router.get("/hotspots")
def hotspots(
    horizon: int = Query(7, ge=0, le=svc.N_HORIZONS, description="0 = observed anomaly, 1..7 = forecast day"),
    min_abs: float = Query(1.0, ge=0, le=20),
    limit: int = Query(50, ge=1, le=500),
    date: str | None = Query(None, pattern=_DATE, description="With horizon=0: observed date inside the stored history"),
) -> dict:
    return _guard(svc.hotspots, horizon, min_abs, limit, date)
