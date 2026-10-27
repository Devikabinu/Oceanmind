"""Marine-heatwave events and statistics, read from the precomputed heatwave results of a processed dataset (oceanmind_model/heatwaves.py).

Methodology is a SIMPLIFIED Hobday et al. (2016) definition; the baseline and thresholds are reported with every payload. It is a project-level indicator, not
an official classification. The detection runs once as a build step per dataset (`python -m oceanmind_model heatwaves ...`); this module only reads and filters
those results, so an API request never touches the multi-year SST record.

Datasets: `ne_pacific` (the original dashboard export, the default) and any dataset known to the environment store (e.g. `pacific`), which keeps its results in
`<processed dir>/model/dashboard/`, separate from the processed environmental cubes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.services import geo_regions as geo
from app.services.environment import OutputsUnavailable, env as load_env

LEGACY_DATASET = "ne_pacific"
FOOTPRINT_MAX_CELLS = 30000          # a footprint is returned whole (the Pacific grid has about 24,000 cells), never thinned into a speckle


@dataclass
class HeatwaveData:
    dataset: str
    info: dict
    state: dict | None
    lat: np.ndarray
    lon: np.ndarray
    res: float


def _results_dir(dataset: str) -> Path:
    from app.services import environment_store as es
    ds = es.resolve_dataset_id(dataset)                      # raises UnknownDataset for an id the backend does not provide
    return es.dataset_refs()[ds].path / "model" / "dashboard"


@lru_cache(maxsize=4)
def _read_dir(path: str, stamp: float) -> tuple[dict, dict | None, np.ndarray, np.ndarray, float]:
    d = Path(path)
    info = json.loads((d / "heatwave.json").read_text())
    state = None
    if (d / "heatwave_state.npz").exists():
        with np.load(d / "heatwave_state.npz") as z:
            state = {k: z[k] for k in z.files}
    g = info["grid"]
    res = float(g["resolution_deg"])
    H, W = (state["active"].shape if state is not None else (0, 0))
    lat = g["lat_min"] + res * np.arange(H)
    lon = g["lon_min"] + res * np.arange(W)
    return info, state, lat, lon, res


def data(dataset: str | None = None) -> HeatwaveData:
    ds = dataset or LEGACY_DATASET
    if ds == LEGACY_DATASET:
        e = load_env()
        if e.hwinfo is None:
            raise OutputsUnavailable("marine-heatwave export not found; run `python -m oceanmind_model export-dashboard`")
        return HeatwaveData(ds, e.hwinfo, e.hw, e.lat, e.lon, e.res)
    d = _results_dir(ds)
    f = d / "heatwave.json"
    if not f.exists():
        raise OutputsUnavailable(f"marine-heatwave results for dataset {ds!r} have not been built; run "
                                 f"`python -m oceanmind_model heatwaves --config <config for {ds}> --dataset-id {ds}`")
    info, state, lat, lon, res = _read_dir(str(d), f.stat().st_mtime + (d / "heatwave_state.npz").stat().st_mtime)
    return HeatwaveData(ds, info, state, lat, lon, res)


def state_for(dataset: str) -> HeatwaveData | None:
    """Heatwave results of a dataset for other services (e.g. ecological risk); None when they have not been built."""
    try:
        return data(dataset)
    except OutputsUnavailable:
        return None


WHAT_IS = ("A marine heatwave is a period when ocean temperatures remain unusually warm for several consecutive days compared "
           "with the expected conditions for that location and time of year.")


def how_detected(info: dict) -> list[str]:
    b0, b1 = info["baseline"]
    where = "the study region only" if info.get("dataset", LEGACY_DATASET) == LEGACY_DATASET else "this dataset's domain"
    return [
        f"Baseline (climatology): for every grid cell and day of the year we use the {b0[:4]}-{b1[:4]} record of this dataset to define the expected temperature.",
        "Threshold: the 90th percentile of SST in an 11-day window around each calendar day, pooled over the baseline years and smoothed over 31 days. "
        "A day is 'unusually warm' when SST exceeds it.",
        "Consecutive days: at least 5 days in a row above the threshold; gaps of up to 2 days are bridged (a missing-data day is not an exceedance, so it can only be "
        "bridged like any other short gap). A run still in progress counts once it is 5 days old.",
        "Events: neighbouring cells that are in a heatwave on the latest day (8-connected, at least 10 cells) are grouped into one event, also across the 180th meridian; "
        "start date, duration, area and anomaly are summarised over its cells.",
        "Intensity and category: intensity is SST minus the baseline mean; the category is the peak intensity divided by (threshold minus baseline mean), "
        "rounded down: I Moderate, II Strong, III Severe, IV Extreme. Cumulative intensity is the sum of daily anomalies over the event (degC-days). "
        "Area is the sum of latitude-dependent cell areas.",
        f"This is the project's own simplified implementation (baseline {b0[:4]}-{b1[:4]}, {where}). It is not an official or operational marine-heatwave warning service.",
    ]


def explain(ev: dict, info: dict) -> list[str]:
    area = ev["area_km2"]
    out = [
        f"Sea surface temperature has been above the seasonal 90th percentile for {ev['duration_days']} days "
        f"(since {ev['start_date']}) over about {area:,.0f} km2.",
        f"The current anomaly averages {ev['current_anomaly_c']:+.1f} degC and peaked at {ev['max_anomaly_c']:+.1f} degC; "
        f"that is {ev['category_name']} on the project's category scale.",
        f"Cumulative intensity so far is about {ev.get('cumulative_intensity_c_days', 0):.0f} degC-days (sum of daily anomalies over the event).",
        f"Today's temperature is higher than {ev['historical_percentile']:.0f}% of baseline-years' values for this time of year.",
    ]
    p = ev.get("forecast_still_above_p90_day7")
    if p is not None:
        out.append(f"The model forecast keeps {p * 100:.0f}% of this area above the 90th-percentile threshold on day 7 (model output, not observation).")
    if info.get("is_observational") is False:
        out.append("The underlying SST is a modelled dataset rather than direct observations, so this event describes that dataset.")
    return out


def _provenance(info: dict) -> dict:
    src = info.get("source")
    return {"dataset": info.get("dataset", LEGACY_DATASET), "provider": src, "is_observational": info.get("is_observational", True),
            "data_source": info["data_source"]}


def summary(d: HeatwaveData | None = None, dataset: str | None = None, n_events: int | None = None) -> dict:
    d = d or data(dataset)
    info = d.info
    return {
        "dataset": d.dataset, "method": info["method"], "baseline": info["baseline"], "data_source": info["data_source"],
        "threshold": info.get("threshold"), "min_duration_days": info.get("min_duration_days", 5), "max_gap_days": info.get("max_gap_days", 2),
        "source": info.get("source"), "is_observational": info.get("is_observational", True),
        "latest_date": info["latest_date"], "active_area_km2": info["active_area_km2"],
        "active_share": info["active_share"], "historical_rank_pct": info["active_area_historical_rank_pct"],
        "n_events": len(info["events"]) if n_events is None else n_events, "ocean_area_km2": info["ocean_area_km2"], "what_is": WHAT_IS,
        "how_detected": how_detected(info), "min_event_cells": info["min_event_cells"],
    }


def _event_mask(d: HeatwaveData, index: int, ev: dict) -> np.ndarray:
    """Cells of an event on the latest day. Exact when the results carry the event label grid; otherwise the active cells inside the event's bounding box."""
    if d.state is not None and "event_label" in d.state:
        return d.state["event_label"] == index
    b = ev["bbox"]
    box = geo.bbox_boxes(b["lat_min"], b["lat_max"], b["lon_min"], b["lon_max"]) if -360 <= b["lon_min"] <= b["lon_max"] <= 360 else ()
    m = geo.box_mask(d.lat, d.lon, box) if box else np.zeros((len(d.lat), len(d.lon)), bool)
    return m & (d.state["active"] if d.state is not None else True)


def list_events(dataset: str | None = None, min_category: int = 1, min_area_km2: float = 0.0, region: str | None = None) -> dict:
    d = data(dataset)
    reg = geo.get_region(region) if region and region != "all" else None
    rmask = geo.region_mask(reg, d.lat, d.lon) if reg is not None else None
    items = []
    for idx, ev in enumerate(d.info["events"], 1):
        if ev["category"] < min_category or ev["area_km2"] < min_area_km2:
            continue
        item = {**ev, "dataset": d.dataset}
        if rmask is not None:
            n_in = int((_event_mask(d, idx, ev) & rmask).sum())
            if n_in == 0:
                continue
            item["cells_in_region"] = n_in
        items.append(item)
    out = {"summary": summary(d, n_events=len(items)), "total": len(items), "items": items, "dataset": d.dataset,
           "provenance": _provenance(d.info)}
    if reg is not None:
        out["region"] = {"id": reg.id, "name": reg.name}
    return out


def events_for(dataset: str | None = None) -> list[dict]:
    """The active events of a dataset in the shape the NE Pacific export always had (start/duration/area/category/centroid/bbox...), for services
    that consume heatwave events (alerts, risk evidence)."""
    return [{**ev, "dataset": data(dataset).dataset} for ev in data(dataset).info["events"]]


def get_event(event_id: str, dataset: str | None = None) -> dict | None:
    d = data(dataset)
    for idx, ev in enumerate(d.info["events"], 1):
        if ev["id"] == event_id:
            m = _event_mask(d, idx, ev)
            ii, jj = np.where(m)
            order = np.arange(len(ii))
            if len(ii) > FOOTPRINT_MAX_CELLS:
                order = np.linspace(0, len(ii) - 1, FOOTPRINT_MAX_CELLS).astype(int)
            lon = d.lon[jj[order]]
            footprint = {"cells": int(len(ii)), "returned": int(len(order)), "lat": [round(float(x), 3) for x in d.lat[ii[order]]],
                         "lon": [round(float(x), 3) for x in lon], "lon_180": [round(float(x), 3) for x in ((lon + 180) % 360) - 180],
                         "resolution_deg": d.res}
            return {"event": {**ev, "dataset": d.dataset}, "explanation": explain(ev, d.info), "summary": summary(d),
                    "yearly": d.info["yearly"], "method": d.info["method"], "footprint": footprint, "provenance": _provenance(d.info)}
    return None


def timeseries(days: int, dataset: str | None = None) -> dict:
    d = data(dataset)
    info = d.info
    s = info["daily"]
    sl = slice(-days, None)
    return {"dataset": d.dataset, "method": info["method"], "unit_area": "km2", "ocean_area_km2": info["ocean_area_km2"],
            "dates": s["dates"][sl], "heatwave_area_km2": s["heatwave_area_km2"][sl],
            "mean_sst": s["mean_sst"][sl], "mean_anomaly": s["mean_anomaly"][sl],
            "yearly": info["yearly"], "provenance": _provenance(info)}


def bbox_segments(bbox: dict) -> list[dict]:
    """A bounding box on a continuous east-longitude axis (e.g. 170..190) as boxes in -180..180, split at the antimeridian, for databases that store -180..180."""
    lo, hi = bbox["lon_min"], bbox["lon_max"]
    if hi <= 180:
        return [bbox]
    if lo >= 180:
        return [{**bbox, "lon_min": lo - 360, "lon_max": hi - 360}]
    return [{**bbox, "lon_min": lo, "lon_max": 180.0}, {**bbox, "lon_min": -180.0, "lon_max": hi - 360}]


def map_layer(dataset: str | None = None, region: str | None = None) -> dict:
    """Current anomaly (degC) of the cells that are in a heatwave on the latest date, as a map grid in the shape of /api/monitor/map (legacy compatible):
    null everywhere else (not heatwave, land, no data), never 0. Restricted to a region; longitudes stay on the dataset's continuous axis."""
    d = data(dataset)
    if d.state is None:
        raise OutputsUnavailable("marine-heatwave state not found; re-run the heatwave build for this dataset")
    reg = geo.get_region(region or "pacific")
    mask = geo.region_mask(reg, d.lat, d.lon)
    if not mask.any():
        raise ValueError("The region does not overlap this dataset")
    rows = np.arange(np.flatnonzero(mask.any(axis=1)).min(), np.flatnonzero(mask.any(axis=1)).max() + 1)
    cols = np.flatnonzero(mask.any(axis=0))
    cols = cols[np.argsort(geo.to_east(d.lon[cols]), kind="stable")]
    sel = np.ix_(rows, cols)
    vals = np.where(d.state["active"] & mask, d.state["cur_anom"], np.nan)[sel]
    lon = d.lon[cols]
    if not np.all(np.diff(lon) > 0):
        lon = geo.to_east(lon)
    fin = vals[np.isfinite(vals)]
    h = d.res / 2
    return {
        "dataset": d.dataset, "layer": "heatwave", "label": "Marine-heatwave anomaly (active areas only)", "kind": "derived", "unit": "degC", "horizon": 0,
        "date": d.info["latest_date"], "diverging": True, "region": {"id": reg.id, "name": reg.name},
        "coverage": {"lat_min": float(d.lat.min() - h), "lat_max": float(d.lat.max() + h), "lon_min": float(d.lon.min() - h), "lon_max": float(d.lon.max() + h)},
        "lat": [round(float(x), 4) for x in d.lat[rows]], "lon": [round(float(x), 4) for x in lon],
        "values": [[None if not np.isfinite(x) else round(float(x), 2) for x in row] for row in vals],
        "min": None if not fin.size else round(float(fin.min()), 2), "max": None if not fin.size else round(float(fin.max()), 2),
        "active_cells": int(fin.size), "provenance": _provenance(d.info),
    }


# ------------------------------------------------------------------------------------------------------------------------------------ history
@dataclass
class HistoryData:
    dataset: str
    info: dict
    events: list[dict]
    by_id: dict
    cells: dict | None
    dates: list[str]


@lru_cache(maxsize=4)
def _read_history(path: str, stamp: float) -> tuple[dict, dict | None]:
    d = Path(path)
    info = json.loads((d / "heatwave_history.json").read_text())
    cells = None
    if (d / "heatwave_cells.npz").exists():
        with np.load(d / "heatwave_cells.npz") as z:
            cells = {k: z[k] for k in z.files}
    return info, cells


def history(dataset: str | None = None) -> HistoryData | None:
    """The historical event table of a dataset; None when the results predate the historical-event build."""
    d = data(dataset)
    if d.dataset == LEGACY_DATASET:
        return None
    folder = _results_dir(d.dataset)
    f = folder / "heatwave_history.json"
    if not f.exists():
        return None
    c = folder / "heatwave_cells.npz"
    info, cells = _read_history(str(folder), f.stat().st_mtime + (c.stat().st_mtime if c.exists() else 0))
    days = [str(x) for x in cells["dates"]] if cells is not None and "dates" in cells else d.info["daily"]["dates"]
    return HistoryData(d.dataset, info, info["events"], {e["id"]: e for e in info["events"]}, cells, days)


def _need_history(dataset: str | None) -> HistoryData:
    h = history(dataset)
    if h is None:
        raise OutputsUnavailable("Historical marine-heatwave events have not been built for this dataset; run the heatwave build (`python -m oceanmind_model export-dashboard`).")
    return h


def _brief(ev: dict) -> dict:
    return {k: v for k, v in ev.items() if k not in ("evolution", "current_event_numbers")}


def _event_cells(h: HistoryData, k: int):
    z = h.cells
    sel = z["ev"] == k
    return z["i"][sel].astype(int), z["j"][sel].astype(int)


def history_list(dataset: str | None = None, year: int | None = None, start: str | None = None, end: str | None = None, min_category: int = 1,
                 region: str | None = None, status: str | None = None, sort: str = "start", limit: int = 100) -> dict:
    h = _need_history(dataset)
    d = data(dataset)
    reg = geo.get_region(region) if region and region != "all" else None
    rmask = geo.region_mask(reg, d.lat, d.lon) if reg is not None else None
    items = []
    for k, ev in enumerate(h.events, 1):
        if ev["category"] < min_category:
            continue
        if status and ev["status"] != status.upper():
            continue
        if year is not None and not (int(ev["start_date"][:4]) <= year <= int(ev["end_date"][:4])):
            continue
        if start and ev["end_date"] < start:
            continue
        if end and ev["start_date"] > end:
            continue
        if rmask is not None and h.cells is not None:
            ii, jj = _event_cells(h, k)
            if not rmask[ii, jj].any():
                continue
        items.append(ev)
    keys = {"start": lambda e: e["start_date"], "duration": lambda e: -e["duration_days"], "area": lambda e: -e["peak_area_km2"], "intensity": lambda e: -e["max_anomaly_c"]}
    items.sort(key=keys.get(sort, keys["start"]), reverse=(sort == "start"))
    by_year: dict[str, int] = {}
    for ev in items:
        by_year[ev["start_date"][:4]] = by_year.get(ev["start_date"][:4], 0) + 1
    return {"dataset": h.dataset, "total": len(items), "items": [_brief(e) for e in items[:limit]], "by_start_year": dict(sorted(by_year.items())),
            "first_date": h.info["first_date"], "last_date": h.info["last_date"], "n_detected": h.info["n_detected"], "n_listed_in_record": h.info["n_kept"],
            "note": f"The {h.info['n_kept']} largest space-time events of the record are listed; smaller events are detected but not listed. Method: {d.info['method']}",
            "provenance": _provenance(d.info), "region": ({"id": reg.id, "name": reg.name} if reg else None)}


def _day_index(h: HistoryData, date: str) -> int:
    try:
        return h.dates.index(date)
    except ValueError:
        from app.services import environment_store as es
        raise es.NoDataForDate(f"No heatwave results for {date}. Available {h.dates[0]} to {h.dates[-1]}.", latest=h.dates[-1], first=h.dates[0])


def history_event(event_id: str, dataset: str | None = None, date: str | None = None) -> dict | None:
    h = _need_history(dataset)
    ev = h.by_id.get(event_id)
    if ev is None:
        return None
    d = data(dataset)
    day = date or ev["peak_date"]
    if not (ev["start_date"] <= day <= ev["end_date"]):
        day = ev["peak_date"]
    k = 1 + h.events.index(ev)
    z = h.cells
    t = _day_index(h, day)
    lo, hi = int(z["offsets"][t]), int(z["offsets"][t + 1])
    sel = z["ev"][lo:hi] == k
    ii, jj = z["i"][lo:hi][sel].astype(int), z["j"][lo:hi][sel].astype(int)
    order = np.arange(len(ii))
    if len(ii) > FOOTPRINT_MAX_CELLS:
        order = np.linspace(0, len(ii) - 1, FOOTPRINT_MAX_CELLS).astype(int)
    lon = d.lon[jj[order]]
    footprint = {"date": day, "cells": int(len(ii)), "returned": int(len(order)), "lat": [round(float(x), 3) for x in d.lat[ii[order]]],
                 "lon": [round(float(x), 3) for x in lon], "lon_180": [round(float(x), 3) for x in ((lon + 180) % 360) - 180],
                 "anomaly_c": [None if x == -32768 else round(float(x) / 100, 2) for x in z["anom"][lo:hi][sel][order]], "resolution_deg": d.res}
    current = None
    if ev["status"] == "ACTIVE":
        nums = ev.get("current_event_numbers") or []
        current = [e["id"] for n, e in enumerate(d.info["events"], 1) if n in nums]
    return {"event": _brief(ev), "evolution": ev["evolution"], "footprint": footprint, "current_event_ids": current, "provenance": _provenance(d.info),
            "summary": summary(d), "explanation": explain_history(ev)}


def explain_history(ev: dict) -> list[str]:
    out = [f"From {ev['start_date']} to {ev['end_date']} ({ev['duration_days']} days) sea surface temperature stayed above the seasonal 90th percentile somewhere in this "
           f"event; at its largest, on {ev['peak_date']}, it covered about {ev['peak_area_km2']:,.0f} km2.",
           f"The anomaly averaged {ev['mean_anomaly_c']:+.1f} degC over the event and reached {ev['max_anomaly_c']:+.1f} degC in the strongest cell: {ev['category_name']} on the project scale."]
    if ev["status"] == "ACTIVE":
        out.append("This event is still active on the latest date. The area has been followed since its first day above; cells joined it at different times, so the current-event page, which counts "
                   "from the typical start of the cells it covers now, can give a shorter duration.")
    else:
        out.append("This event had ended by the latest date.")
    return out


def map_layer_on(dataset: str | None, region: str | None, date: str | None) -> dict:
    """Heatwave anomaly layer for any date of the record (the current-date layer when `date` is the latest day or omitted)."""
    d = data(dataset)
    if date is None or date == d.info["latest_date"]:
        return map_layer(dataset, region)
    h = _need_history(dataset)
    t = _day_index(h, date)
    z = h.cells
    lo, hi = int(z["offsets"][t]), int(z["offsets"][t + 1])
    H, W = len(d.lat), len(d.lon)
    grid = np.full((H, W), np.nan, dtype="float32")
    raw = z["anom"][lo:hi].astype("float32")
    grid[z["i"][lo:hi].astype(int), z["j"][lo:hi].astype(int)] = np.where(raw == -32768, np.nan, raw / 100.0)             # -32768 marks a day bridged over missing data
    reg = geo.get_region(region or "pacific")
    mask = geo.region_mask(reg, d.lat, d.lon)
    if not mask.any():
        raise ValueError("The region does not overlap this dataset")
    rows = np.arange(np.flatnonzero(mask.any(axis=1)).min(), np.flatnonzero(mask.any(axis=1)).max() + 1)
    cols = np.flatnonzero(mask.any(axis=0))
    cols = cols[np.argsort(geo.to_east(d.lon[cols]), kind="stable")]
    vals = np.where(mask, grid, np.nan)[np.ix_(rows, cols)]
    lon = d.lon[cols]
    if not np.all(np.diff(lon) > 0):
        lon = geo.to_east(lon)
    fin = vals[np.isfinite(vals)]
    hh = d.res / 2
    return {"dataset": d.dataset, "layer": "heatwave", "label": "Marine-heatwave anomaly (heatwave areas only)", "kind": "derived", "unit": "degC", "horizon": 0, "date": date,
            "diverging": True, "region": {"id": reg.id, "name": reg.name},
            "coverage": {"lat_min": float(d.lat.min() - hh), "lat_max": float(d.lat.max() + hh), "lon_min": float(d.lon.min() - hh), "lon_max": float(d.lon.max() + hh)},
            "lat": [round(float(x), 4) for x in d.lat[rows]], "lon": [round(float(x), 4) for x in lon],
            "values": [[None if not np.isfinite(x) else round(float(x), 2) for x in row] for row in vals],
            "min": None if not fin.size else round(float(fin.min()), 2), "max": None if not fin.size else round(float(fin.max()), 2),
            "active_cells": int(fin.size), "provenance": _provenance(d.info)}


def events_on(dataset: str | None, date: str) -> list[dict]:
    """Historical events in progress on `date`, with the number of cells they occupy that day."""
    h = _need_history(dataset)
    t = _day_index(h, date)
    z = h.cells
    lo, hi = int(z["offsets"][t]), int(z["offsets"][t + 1])
    ids, counts = np.unique(z["ev"][lo:hi], return_counts=True)
    return [{**_brief(h.events[int(k) - 1]), "cells_on_date": int(c)} for k, c in zip(ids, counts)]
