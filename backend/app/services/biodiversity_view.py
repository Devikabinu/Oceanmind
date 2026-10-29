"""The OBIS biodiversity block of the location report: counts, groups, species with conservation status and distance, and the overlap of the recorded places with the current marine
heatwave and with the forecast anomaly area. Every figure is a count of OBIS records; an occurrence record is evidence that an animal was recorded there on that day, not that it
is there today and not that it is harmed. Exposure is potential exposure to the observed or predicted thermal conditions, nothing more."""
from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.species import Species
from app.services import obis_service as osv

FORECAST_EXPOSURE_C = 1.0         # a place is in the predicted warm / cold area when its mean forecast anomaly is at least this large
ITEMS_SHOWN = 24
SCOPE_WORD = {"local": "Local observation", "nearby": "Nearby observation", "regional": "Regional occurrence", "regional Pacific": "Regional occurrence"}


def _recency(latest: str | None, today: date) -> str:
    if not latest:
        return "Historical observation"
    return "Recent observation" if date.fromisoformat(latest) >= today - timedelta(days=osv.RECENT_DAYS) else "Historical observation"


def _area_km2(half_deg: float, lat: float) -> float:
    return (2 * half_deg * 111.32) * (2 * half_deg * 111.32 * max(math.cos(math.radians(lat)), 0.05))


def overlaps(records: list, inp, hw_active, forecast_mean) -> dict:
    """Per species and in total: how many recorded places lie inside the heatwave footprint and inside the predicted anomaly area. Because observers cluster (one bay can hold a third of all
    records), the shares are given by record, by distinct 0.25 degree grid cell and by species, and the densest cell's share of the records is reported so that a record share is never
    mistaken for the share of the region."""
    per: dict[str, dict] = {}
    cells: dict[tuple, dict] = {}
    n_in = hw_n = fc_n = 0
    hw_sp: set = set()
    fc_sp: set = set()
    all_sp: set = set()
    cats: dict[str, str] = {}
    for la, lo, name, _d, cat in records:
        c = inp.cell(la, lo)
        if c is None or not np.isfinite(inp.anomaly[c]):
            continue
        in_hw = hw_active is not None and bool(hw_active[c])
        in_fc = forecast_mean is not None and bool(np.isfinite(forecast_mean[c])) and abs(float(forecast_mean[c])) >= FORECAST_EXPOSURE_C
        n_in += 1
        all_sp.add(name)
        e = per.setdefault(name, {"in_domain": 0, "in_heatwave": 0, "forecast_exposed": 0})
        e["in_domain"] += 1
        ce = cells.setdefault((int(c[0]), int(c[1])), {"n": 0, "hw": in_hw, "fc": in_fc})
        ce["n"] += 1
        if cat:
            cats[name] = cat
        if in_hw:
            e["in_heatwave"] += 1
            hw_n += 1
            hw_sp.add(name)
        if in_fc:
            e["forecast_exposed"] += 1
            fc_n += 1
            fc_sp.add(name)
    thr = lambda s: sum(1 for n in s if cats.get(n) in osv.THREATENED)           # noqa: E731
    pct = lambda k, n: None if not n else round(100.0 * k / n, 1)                # noqa: E731
    n_cells = len(cells)
    top = max((c["n"] for c in cells.values()), default=0)

    def share(avail, records_n, sp_set, cells_n):
        return {"available": avail, "records": records_n, "species": len(sp_set), "threatened_species": thr(sp_set), "share_pct": pct(records_n, n_in),
                "cells": cells_n, "cells_share_pct": pct(cells_n, n_cells), "species_share_pct": pct(len(sp_set), len(all_sp))}
    return {"per_species": per, "records_in_domain": n_in, "species_in_domain": len(all_sp), "cells_in_domain": n_cells, "densest_cell_share_pct": pct(top, n_in),
            "heatwave": share(hw_active is not None, hw_n, hw_sp, sum(1 for c in cells.values() if c["hw"])),
            "forecast": {**share(forecast_mean is not None, fc_n, fc_sp, sum(1 for c in cells.values() if c["fc"])), "threshold_c": FORECAST_EXPOSURE_C}}


def view(db: Session, bio: dict | None, lat: float, inp=None, hw_active=None, today: date | None = None) -> dict | None:
    """The report block, or None when OBIS gave nothing (the stored records are then used by the caller)."""
    if bio is None:
        return None
    if not bio.get("available"):
        return {"available": False, "status": bio.get("status"), "message": bio.get("message")}
    today = today or date.today()
    species = bio["species"]
    cat = {s.aphia_id: s for s in db.execute(select(Species).where(Species.aphia_id.in_([x["aphia_id"] for x in species[:200] if x.get("aphia_id")]))).scalars()}
    fm = None
    if inp is not None and inp.forecast_anomaly is not None:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            fm = np.nanmean(inp.forecast_anomaly, axis=0)
    ov = overlaps(bio["records"], inp, hw_active, fm) if inp is not None else None
    scope = bio["scope"]
    def item(s):
        sp = cat.get(s.get("aphia_id"))
        o = (ov or {}).get("per_species", {}).get(s["scientific_name"], {})
        return {"scientific_name": s["scientific_name"], "common_name": sp.common_name if sp else None, "group": s["group"], "conservation_status": s["category"] or "Not assessed",
                "threatened": s["category"] in osv.THREATENED, "records": s["records"], "nearest_km": s["nearest_km"], "latest_record": s["latest_record"],
                "recency": _recency(s["latest_record"], today), "scope_label": SCOPE_WORD[scope], "records_in_heatwave": o.get("in_heatwave") if ov and ov["heatwave"]["available"] else None,
                "records_in_forecast_area": o.get("forecast_exposed") if ov and ov["forecast"]["available"] else None, "sampled_records": s["sampled_records"], "datasets": s["datasets"]}
    items = [item(s) for s in species[:ITEMS_SHOWN]]
    threatened = [item(s) for s in species if s["category"] in osv.THREATENED][:20]
    groups = Counter(s["group"] for s in species if s["group"])
    gr_rec: Counter = Counter()
    for s in species:
        if s["group"]:
            gr_rec[s["group"]] += s["records"]
    half = bio["half_width_deg"]
    n_recent = bio["records_in_box"]
    area = _area_km2(half, lat)
    fetched = datetime.fromisoformat(bio["fetched_at"])
    label = (f"{SCOPE_WORD[scope].split()[0]} records within about {half:g}° of this location" + (" (older records included)" if bio["historical"] else " (last 2 years)")
             + f": {n_recent:,} observations of {len(species):,} species.")
    exposure_text = None
    if ov and ov["records_in_domain"]:
        hwx, fcx = ov["heatwave"], ov["forecast"]
        parts = []
        cells_n, sp_n = ov["cells_in_domain"], ov["species_in_domain"]
        if hwx["available"] and not hwx["species"]:
            parts.append(f"None of the {sp_n} recorded species has records inside the current marine-heatwave footprint (the {cells_n} recorded grid cells lie outside it).")
        elif hwx["available"]:
            parts.append(f"{hwx['species']} of {sp_n} recorded species ({hwx['species_share_pct']}%) have records inside the current marine-heatwave footprint, at {hwx['cells']} of {cells_n} recorded grid cells ({hwx['cells_share_pct']}%)"
                         + (f"; {hwx['threatened_species']} of them are listed as threatened in the IUCN Red List category carried by OBIS" if hwx["species"] else "") + ".")
        if fcx["available"] and not fcx["species"]:
            parts.append(f"Potential forecast exposure: no recorded species has records where the model predicts a mean anomaly of at least {FORECAST_EXPOSURE_C:g} °C in either direction over the next 7 days.")
        elif fcx["available"]:
            parts.append(f"Potential forecast exposure: {fcx['species']} species have records at {fcx['cells']} of {cells_n} grid cells ({fcx['cells_share_pct']}%) where the model predicts a mean anomaly of at least "
                         f"{FORECAST_EXPOSURE_C:g} °C in either direction over the next 7 days, {fcx['threatened_species']} of them threatened.")
        if ov["densest_cell_share_pct"] is not None and ov["densest_cell_share_pct"] >= 40:
            parts.append(f"Caution: {ov['densest_cell_share_pct']:.0f}% of the matched records come from one 0.25° grid cell, so the share of records mostly describes that cell; the shares by cells and by species are the better guide.")
        exposure_text = " ".join(parts) + " These records indicate potential exposure to the observed or predicted thermal conditions; they are not evidence of biological damage."
    return {"available": True, "status": bio["status"], "scope": scope, "scope_label": SCOPE_WORD[scope], "half_width_deg": half, "historical": bio["historical"],
            "window": {"start": bio["window_start"], "end": today.isoformat()}, "label": label, "trail": bio["trail"],
            "counts": {"observations": n_recent, "observations_all_time": bio["records_all_time"], "distinct_species": len(species), "threatened_species": sum(1 for s in species if s["category"] in osv.THREATENED),
                       "taxa": bio["taxa"], "sampled_records": bio["sampled_records"], "density_per_1000_km2": round(1000.0 * n_recent / area, 2)},
            "groups": [{"group": g, "species": n, "records": gr_rec[g]} for g, n in groups.most_common(8)], "items": items, "threatened": threatened,
            "exposure": None if ov is None else {k: v for k, v in ov.items() if k != "per_species"}, "exposure_text": exposure_text,
            "provenance": {"source": "Ocean Biodiversity Information System (OBIS)", "dataset": "OBIS occurrence and checklist API v3", "url": bio["api"], "retrieved": fetched.date().isoformat(),
                           "observation_dates": f"{'all years' if bio['historical'] else bio['window_start']} to {today.isoformat()}", "spatial_resolution": "point occurrence records (box of ±%g°)" % half,
                           "temporal_resolution": "individual observation dates", "conservation_source": "IUCN Red List category as carried by OBIS", "cache": bio["status"]},
            "caveats": ["An occurrence record shows where and when an animal was recorded, not its range and not that it is there today.", "OBIS records are unevenly sampled: dense coasts and tourist areas, sparse open ocean."]}
