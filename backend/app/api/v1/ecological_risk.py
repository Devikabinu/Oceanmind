"""Explainable project environmental / ecological risk indicator (see services/risk_service.py for the method)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from sqlalchemy import select

from app.models.species import Species
from app.services import risk_service as risk
from app.services.monitor_service import REGIONS
from app.services.environment import OutputsUnavailable, env as load_env

router = APIRouter(prefix="/ecological-risk", tags=["ecological-risk"], dependencies=[Depends(get_current_user)])


@router.get("/methodology")
def methodology() -> dict:
    return risk.METHODOLOGY


@router.get("/location")
def location_risk(lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180),
                  db: Session = Depends(get_db)) -> dict:
    try:
        e = load_env()
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    c = e.cell(lat, lon)
    if c is None:
        raise HTTPException(status_code=404, detail="Outside the study-region grid: no risk can be assessed here")
    if not e.is_ocean(*c):
        raise HTTPException(status_code=404, detail="No ocean data at this location (land)")
    return {"cell": {"lat": round(float(e.lat[c[0]]), 3), "lon": round(float(e.lon[c[1]]), 3)},
            "date": e.info["latest"]["observed_date"], "methodology": risk.METHODOLOGY["name"],
            **risk.cell_assessment(e, c[0], c[1], risk.species_overlap_blocks(db, e))}


@router.get("/areas")
def risk_areas(min_level: str = Query("HIGH", pattern="^(LOW|MEDIUM|HIGH|CRITICAL)$"), limit: int = Query(30, ge=1, le=200),
               region: str = Query("all", pattern="^(all|north|south|west|east)$"), db: Session = Depends(get_db)) -> dict:
    """Highest-scoring 2x2 degree blocks (block mean of the cell scores), with their dominant driver."""
    try:
        e = load_env()
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    import numpy as np
    g = risk.factor_grids(e, risk.species_overlap_blocks(db, e))
    score = g["score"]
    B = risk.BLOCK
    order = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    rows = []
    for i in range(0, score.shape[0], B):
        for j in range(0, score.shape[1], B):
            blk = score[i:i + B, j:j + B]
            ok = ~np.isnan(blk)
            if ok.sum() < B * B * 0.25:
                continue
            mean = float(blk[ok].mean())
            lv = risk.level_for(mean)
            if order.index(lv) < order.index(min_level):
                continue
            la0, la1, lo0, lo1 = REGIONS[region]
            clat, clon = float(e.lat[i:i + B].mean()), float(e.lon[j:j + B].mean())
            if not (la0 <= clat <= la1 and lo0 <= clon <= lo1):
                continue
            drivers = {k: float(np.nanmean(v[i:i + B, j:j + B])) for k, v in g["factors"].items() if v is not None}
            top = max(drivers, key=drivers.get)
            la, lo = e.lat[i:i + B], e.lon[j:j + B]
            rows.append({"lat": round(float((la[0] + la[-1]) / 2), 2), "lon": round(float((lo[0] + lo[-1]) / 2), 2),
                         "score": round(mean, 3), "level": lv, "top_driver": top,
                         "factors": {k: round(v, 3) for k, v in drivers.items()},
                         "bbox": {"lat_min": float(la[0]) - 0.125, "lat_max": float(la[-1]) + 0.125,
                                  "lon_min": float(lo[0]) - 0.125, "lon_max": float(lo[-1]) + 0.125}})
    rows.sort(key=lambda r: -r["score"])
    return {"date": e.info["latest"]["observed_date"], "methodology": risk.METHODOLOGY["name"], "region": region, "total": len(rows),
            "items": rows[:limit], "factors_used": g["used"]}


@router.get("/species")
def species_ranking(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)) -> dict:
    """Catalogued species ranked by the project environmental risk indicator of their recent study-region records
    (potential exposure, not harm). Species without recent records are listed as unavailable, not scored."""
    try:
        e = load_env()
    except OutputsUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    items = []
    for sp in db.execute(select(Species)).scalars():
        a = risk.species_assessment(db, e, sp.aphia_id, sp.scientific_name)
        items.append({**a, "common_name": sp.common_name, "taxon_group": sp.taxon_group, "iucn_category": sp.iucn_category})
    items.sort(key=lambda a: (not a["available"], -(a.get("score") or 0)))
    return {"items": items[:limit], "methodology": risk.METHODOLOGY["name"]}
