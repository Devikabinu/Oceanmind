"""Explainable project environmental / ecological risk indicator (see services/risk_service.py for the method).

Every endpoint takes an optional `dataset`. Omitted or `ne_pacific`: the original NE Pacific behaviour, unchanged. `pacific`: the same methodology on the
Pacific-wide processed environmental dataset (factors that dataset cannot supply are reported as unavailable, never as zero)."""
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.v1.environment import guard
from app.models.species import Species
from app.services import geo_regions as geo
from app.services import risk_service as risk
from app.services.environment import OutputsUnavailable, env as load_env
from app.services.monitor_service import REGIONS

router = APIRouter(prefix="/ecological-risk", tags=["ecological-risk"], dependencies=[Depends(get_current_user)])

_DATE = r"^(\d{4}-\d{2}-\d{2}|latest)$"
LEGACY_REGIONS = tuple(REGIONS)


def _is_legacy(dataset: str | None) -> bool:
    return dataset in (None, risk.LEGACY_DATASET)


def _legacy_env():
    try:
        return load_env()
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))


def _inputs(dataset: str | None, date: str | None):
    """Risk inputs for a dataset; NE Pacific uses the dashboard export and ignores `date` (it only has its latest day)."""
    if _is_legacy(dataset):
        return risk.legacy_inputs(_legacy_env())
    return guard(risk.inputs_for, dataset, date)


@router.get("/methodology")
def methodology(dataset: str | None = None) -> dict:
    if _is_legacy(dataset) and dataset is None:
        return risk.METHODOLOGY
    return {**risk.METHODOLOGY, "dataset_capabilities": guard(risk.dataset_capabilities, dataset)}


@router.get("/location")
def location_risk(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-360, le=360), dataset: str | None = None,
                  date: str | None = Query(None, pattern=_DATE), db: Session = Depends(get_db)) -> dict:
    if _is_legacy(dataset):
        if not (-180 <= lon <= 180):
            raise HTTPException(status_code=422, detail="lon must be between -180 and 180 for the NE Pacific dataset")
        e = _legacy_env()
        c = e.cell(lat, lon)
        if c is None:
            raise HTTPException(status_code=404, detail="Outside the study-region grid: no risk can be assessed here")
        if not e.is_ocean(*c):
            raise HTTPException(status_code=404, detail="No ocean data at this location (land)")
        return {"cell": {"lat": round(float(e.lat[c[0]]), 3), "lon": round(float(e.lon[c[1]]), 3)},
                "date": e.info["latest"]["observed_date"], "methodology": risk.METHODOLOGY["name"],
                **risk.cell_assessment(e, c[0], c[1], risk.species_overlap_blocks(db, e))}
    inp = _inputs(dataset, date)
    c = inp.cell(lat, lon)
    if c is None:
        raise HTTPException(status_code=404, detail=f"Outside the {inp.dataset!r} dataset: no risk can be assessed here")
    if int(inp.state[c]) == risk.LAND:
        raise HTTPException(status_code=404, detail="No ocean data at this location (land)")
    overlap = risk.species_overlap_blocks(db, inp)
    g = risk.factor_grids(inp, overlap)
    return {"dataset": inp.dataset, "source": inp.source, "cell": {"lat": round(float(inp.lat[c[0]]), 3), "lon": round(float(inp.lon[c[1]]), 3),
                                                              "lon_180": round(float(((inp.lon[c[1]] + 180) % 360) - 180), 3)},
            "date": inp.date, "methodology": risk.METHODOLOGY["name"], **risk.cell_assessment(inp, c[0], c[1], overlap, g)}


@router.get("/explain")
def explain_cell(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-360, le=360), dataset: str | None = None,
                 date: str | None = Query(None, pattern=_DATE), db: Session = Depends(get_db)) -> dict:
    """Plain-language explanation of one risk cell, built only from the structured result of /location (no model, nothing invented)."""
    from app.services import explain_service
    cell = location_risk(lat, lon, dataset, date, db)
    if _is_legacy(dataset):
        cell = {**cell, "dataset": risk.LEGACY_DATASET, "source": risk.legacy_inputs(_legacy_env()).source,
                "cell": {**cell["cell"], "lon_180": cell["cell"]["lon"]}}
    return {"cell": cell, "explanation": explain_service.explain_risk_cell(cell)}


@router.get("/map")
def risk_map(dataset: str | None = None, region: str = "pacific", date: str | None = Query(None, pattern=_DATE),
             max_cells: int = Query(30000, ge=100, le=200000), db: Session = Depends(get_db)) -> dict:
    """Risk grid for a dataset and region (map-sized). Land, missing and insufficient cells are explicit states, never 0."""
    if _is_legacy(dataset):
        _legacy_env()
    return guard(risk.risk_map, db, dataset or risk.LEGACY_DATASET, region, date, max_cells)


@router.get("/areas")
def risk_areas(min_level: str = Query("HIGH", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"), limit: int = Query(30, ge=1, le=200),
               region: str = Query("all"), dataset: str | None = None, date: str | None = Query(None, pattern=_DATE),
               db: Session = Depends(get_db)) -> dict:
    """Highest-scoring 2x2 degree blocks (block mean of the cell scores), with their dominant driver. `region`: NE Pacific names (all, north, south, west,
    east) for the NE dataset, or a region id from /api/environment/regions for any dataset."""
    legacy = _is_legacy(dataset)
    if legacy and region in LEGACY_REGIONS:
        in_region = lambda clat, clon: REGIONS[region][0] <= clat <= REGIONS[region][1] and REGIONS[region][2] <= clon <= REGIONS[region][3]  # noqa: E731
    else:
        if legacy and region not in geo.REGIONS and region != "all":
            raise HTTPException(status_code=422, detail=f"unknown region {region!r}")          # the original contract for the NE Pacific dataset
        if region == "all":
            region = "pacific"
        reg = guard(geo.get_region, region)
        in_region = lambda clat, clon: bool(geo.region_mask(reg, [clat], [clon])[0, 0])  # noqa: E731
    inp = _inputs(dataset, date)
    g = risk.factor_grids(inp, risk.species_overlap_blocks(db, inp))
    score = g["score"]
    B = inp.block
    order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    half = inp.res / 2
    rows = []
    for i in range(0, score.shape[0], B):
        for j in range(0, score.shape[1], B):
            blk = score[i:i + B, j:j + B]
            ok = ~np.isnan(blk)
            if ok.sum() < max(1, B * B * 0.25):
                continue
            mean = float(blk[ok].mean())
            lv = risk.level_for(mean)
            if order.index(lv) < order.index(min_level):
                continue
            clat, clon = float(inp.lat[i:i + B].mean()), float(inp.lon[j:j + B].mean())
            if not in_region(clat, clon):
                continue
            drivers = {k: float(np.nanmean(v[i:i + B, j:j + B])) for k, v in g["factors"].items() if v is not None and np.isfinite(v[i:i + B, j:j + B]).any()}
            top = max(drivers, key=drivers.get)
            la, lo = inp.lat[i:i + B], inp.lon[j:j + B]
            rows.append({"lat": round(float((la[0] + la[-1]) / 2), 2), "lon": round(float((lo[0] + lo[-1]) / 2), 2),
                         "lon_180": round(float((((lo[0] + lo[-1]) / 2 + 180) % 360) - 180), 2),
                         "score": round(mean, 3), "level": lv, "top_driver": top,
                         "factors": {k: round(v, 3) for k, v in drivers.items()},
                         "bbox": {"lat_min": float(la[0]) - half, "lat_max": float(la[-1]) + half,
                                  "lon_min": float(lo[0]) - half, "lon_max": float(lo[-1]) + half}})
    rows.sort(key=lambda r: -r["score"])
    return {"date": inp.date, "dataset": inp.dataset, "methodology": risk.METHODOLOGY["name"], "region": region, "total": len(rows),
            "items": rows[:limit], "factors_used": g["used"], "factors_unavailable": dict(inp.unavailable), "source": inp.source}


@router.get("/species")
def species_ranking(limit: int = Query(30, ge=1, le=100), dataset: str | None = None, date: str | None = Query(None, pattern=_DATE),
                    db: Session = Depends(get_db)) -> dict:
    """Catalogued species ranked by the project environmental risk indicator of their recent records inside the dataset domain
    (potential exposure, not harm). Species without recent records are listed as insufficient data, not scored."""
    inp = _inputs(dataset, date)
    items = []
    for sp in db.execute(select(Species)).scalars():
        a = risk.species_assessment(db, inp, sp.aphia_id, sp.scientific_name)
        items.append({**a, "common_name": sp.common_name, "taxon_group": sp.taxon_group, "iucn_category": sp.iucn_category,
                      "conservation_status": sp.iucn_category or "Status not confirmed"})
    items.sort(key=lambda a: (not a["available"], -(a.get("score") or 0)))
    return {"items": items[:limit], "methodology": risk.METHODOLOGY["name"], "dataset": inp.dataset, "date": inp.date}
