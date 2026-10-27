"""Pacific-wide processed environmental data: datasets, regions, dates, coverage and map-sized SST / SST-anomaly grids (file-backed, no DB tables)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.services import environment_store as store
from app.services import geo_regions as geo

router = APIRouter(prefix="/environment", tags=["environment"], dependencies=[Depends(get_current_user)])

_DATE = r"^(\d{4}-\d{2}-\d{2}|latest)$"
Layer = Literal["sst", "anomaly"]


def parse_bbox(min_lat, max_lat, min_lon, max_lon):
    given = [v is not None for v in (min_lat, max_lat, min_lon, max_lon)]
    if not any(given):
        return None
    if not all(given):
        raise HTTPException(422, detail={"code": "invalid_bounds", "message": "min_lat, max_lat, min_lon and max_lon must be given together"})
    try:
        geo.bbox_boxes(min_lat, max_lat, min_lon, max_lon)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_bounds", "message": str(exc)})
    return (min_lat, max_lat, min_lon, max_lon)


def guard(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except store.UnknownDataset as exc:
        raise HTTPException(404, detail={"code": "unknown_dataset", "message": str(exc)})
    except geo.UnknownRegion as exc:
        raise HTTPException(404, detail={"code": "unknown_region", "message": str(exc.args[0])})
    except store.NoDataForDate as exc:
        raise HTTPException(404, detail={"code": "no_data_for_date", "message": str(exc), "latest_available_date": exc.latest,
                                         "available_range": {"first": exc.first, "last": exc.latest}})
    except store.UnknownLayer as exc:
        raise HTTPException(422, detail={"code": "unknown_layer", "message": str(exc)})
    except store.DatasetUnavailable as exc:
        raise HTTPException(503, detail={"code": "dataset_unavailable", "message": str(exc)})
    except ValueError as exc:
        raise HTTPException(422, detail={"code": "invalid_request", "message": str(exc)})


@router.get("/datasets")
def datasets() -> dict:
    return {"default": store.default_dataset_id(), "datasets": store.list_datasets()}


@router.get("/regions")
def regions() -> dict:
    return {"regions": [geo.describe(r) for r in geo.REGIONS.values()]}


@router.get("/dates")
def dates(dataset: str | None = None) -> dict:
    def run():
        s = store.get_store(dataset)
        return {"dataset": s.ref.id, "latest_date": str(s.dates[-1].date()), "first_date": str(s.dates[0].date()), "n_dates": int(len(s.dates)),
                "provider": s.source}
    return guard(run)


@router.get("/coverage")
def coverage(dataset: str | None = None, layer: Layer = "sst", date: str | None = Query(None, pattern=_DATE), region: str = "pacific",
             min_lat: float | None = None, max_lat: float | None = None, min_lon: float | None = None, max_lon: float | None = None) -> dict:
    bbox = parse_bbox(min_lat, max_lat, min_lon, max_lon)
    return guard(store.coverage_response, dataset, layer, date, region, bbox)


@router.get("/map")
def environment_map(dataset: str | None = None, layer: Layer = "sst", date: str | None = Query(None, pattern=_DATE), region: str = "pacific",
                    min_lat: float | None = None, max_lat: float | None = None, min_lon: float | None = None, max_lon: float | None = None,
                    max_cells: int = Query(20000, ge=100, le=200000), include_status: bool = False) -> dict:
    bbox = parse_bbox(min_lat, max_lat, min_lon, max_lon)
    return guard(store.map_response, dataset, layer, date, region, bbox, max_cells, include_status)


@router.get("/point")
def environment_point(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-360, le=360), dataset: str | None = None,
                      date: str | None = Query(None, pattern=_DATE), layer: Layer | None = None) -> dict:
    """Values at one clicked coordinate (lon in -180..180 or 0..360). No-data answers (outside dataset, land, missing) are 200 with a `status`, like /monitor/location."""
    return guard(store.point_response, dataset, lat, lon, date, layer)


@router.get("/forecast")
def environment_forecast(dataset: str = "pacific", region: str = "pacific", db: Session = Depends(get_db)) -> dict:
    """Regional-mean ConvLSTM forecast of a dataset other than the NE Pacific, with the model provenance and the performance measured on that dataset, the continuation of
    active marine heatwaves and what it means for ecological risk."""
    from app.services import forecast_store
    from app.services.environment import OutputsUnavailable
    try:
        out = guard(forecast_store.forecast, dataset, region)
    except OutputsUnavailable as exc:
        raise HTTPException(503, detail={"code": "forecast_unavailable", "message": str(exc)})
    out["risk_implication"] = _risk_implication(db, dataset, region, out)
    out["explanation"]["sections"].append({"id": "risk", "title": "What it means for ecological risk", "text": out["risk_implication"]["message"], "bullets": out["risk_implication"].get("bullets", [])})
    return out


def _risk_implication(db: Session, dataset: str, region: str, f: dict) -> dict:
    """Plain statement of how the forecast bears on ecological risk: how many areas of the region are at HIGH or CRITICAL risk on the forecast's start date, and whether the
    forecast keeps heat above the heatwave threshold there. Risk is a project indicator of potential exposure, never of harm."""
    from app.api.v1.ecological_risk import risk_areas
    try:
        areas = risk_areas(min_level="HIGH", limit=200, region=region if region != "pacific" else "all", dataset=dataset, date=f["issued_from"], db=db)
    except HTTPException:
        return {"available": False, "message": "Ecological risk could not be assessed for the date the forecast was issued from, so no implication is drawn."}
    n = len(areas["items"])
    hc = f.get("heatwave_continuation") or {}
    count = f"At least {n}" if n >= 200 else str(n)                                  # the listing is capped at 200 areas
    bullets = [f"{count} area(s) of {f['region']['name']} are at HIGH or CRITICAL ecological risk on {f['issued_from']}."]
    if hc.get("share_still_above_day7") is not None:
        bullets.append(f"The forecast keeps {hc['share_still_above_day7'] * 100:.0f}% of the active marine-heatwave area above the threshold on day 7, so the heat-related part of that risk "
                       f"{'is likely to persist' if hc['share_still_above_day7'] >= 0.5 else 'may ease'} (model prediction).")
    else:
        bullets.append("The forecast could not be compared with the heatwave threshold, so no statement is made about whether the heat-related risk persists.")
    return {"available": True, "areas_high_or_critical": n, "message": "Ecological risk is a project indicator of potential exposure, not evidence of harm. " + bullets[0], "bullets": bullets}


@router.get("/forecast/map")
def environment_forecast_map(dataset: str = "pacific", horizon: int = Query(1, ge=1, le=14), region: str = "pacific", kind: Literal["sst", "anomaly"] = "sst") -> dict:
    from app.services import forecast_store
    from app.services.environment import OutputsUnavailable
    try:
        return guard(forecast_store.forecast_map, dataset, horizon, region, kind)
    except OutputsUnavailable as exc:
        raise HTTPException(503, detail={"code": "forecast_unavailable", "message": str(exc)})


@router.get("/summary")
def environment_summary(dataset: str | None = None, layer: Layer = "sst", date: str | None = Query(None, pattern=_DATE), region: str = "pacific") -> dict:
    """Area-weighted regional mean / extremes of SST or anomaly on a date, with coverage and provenance: the headline numbers of the dashboard."""
    return guard(store.summary_response, dataset, layer, date, region)


@router.get("/anomaly-analysis")
def anomaly_analysis(dataset: str | None = None, date: str | None = Query(None, pattern=_DATE), region: str = "pacific", top: int = Query(8, ge=1, le=20)) -> dict:
    """Strongest warm and cold anomalies, persistent anomalies, the regional anomaly timeline and a regional comparison for one date."""
    from app.services import anomaly_analysis as aa
    return guard(aa.analysis, dataset, date, region, top)


@router.get("/report")
def environment_report(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-360, le=360), dataset: str | None = None,
                       date: str | None = Query(None, pattern=_DATE), db: Session = Depends(get_db)) -> dict:
    """Everything known about one place on the map, for one dataset and date: conditions, anomaly and its explanation, marine-heatwave status, ecological risk and its drivers,
    species nearby and their exposure, forecast and alerts."""
    from app.services import location_report
    return guard(location_report.report, db, dataset, lat, lon, date)


@router.get("/species-exposure")
def environment_species_exposure(aphia_id: int, dataset: str | None = None, date: str | None = Query(None, pattern=_DATE), db: Session = Depends(get_db)) -> dict:
    from app.services import location_report
    return guard(location_report.species_exposure, db, dataset, aphia_id, date)


@router.get("/species-layer")
def environment_species_layer(dataset: str | None = None, region: str = "pacific", date: str | None = Query(None, pattern=_DATE), db: Session = Depends(get_db)) -> dict:
    from app.services import location_report
    return guard(location_report.species_layer, db, dataset, region, date)
