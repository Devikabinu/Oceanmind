"""Marine-heatwave events and statistics, read from the ML pipeline export (oceanmind_model/heatwaves.py).

Methodology is a SIMPLIFIED Hobday et al. (2016) definition with a 12-year baseline; see the `method` string returned
with every payload. It is a project-level indicator, not an official classification.
"""
from __future__ import annotations

from app.services.environment import Env, OutputsUnavailable, env as load_env


def _hw() -> tuple[Env, dict]:
    e = load_env()
    if e.hwinfo is None:
        raise OutputsUnavailable("marine-heatwave export not found; run `python -m oceanmind_model export-dashboard`")
    return e, e.hwinfo


WHAT_IS = ("A marine heatwave is a period when ocean temperatures remain unusually warm for several consecutive days compared "
           "with the expected conditions for that location and time of year.")

HOW_DETECTED = [
    "Baseline (climatology): for every grid cell and day of the year we use the 2012-2023 NOAA OISST record to define the expected temperature.",
    "Threshold: the 90th percentile of SST in an 11-day window around each calendar day, pooled over the baseline years and smoothed over 31 days. "
    "A day is 'unusually warm' when SST exceeds it.",
    "Consecutive days: at least 5 days in a row above the threshold; gaps of up to 2 days are bridged. A run still in progress counts once it is 5 days old.",
    "Events: neighbouring cells that are in a heatwave on the latest day (8-connected, at least 10 cells) are grouped into one event; start date, duration, area and "
    "anomaly are summarised over its cells.",
    "Intensity and category: intensity is SST minus the baseline mean; the category is the peak intensity divided by (threshold minus baseline mean), "
    "rounded down: I Moderate, II Strong, III Severe, IV Extreme. Cumulative intensity is the sum of daily anomalies over the event (degC-days).",
    "This is the project's own simplified implementation (12-year baseline, study region only). It is not an official or operational marine-heatwave warning service.",
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
    return out


def summary() -> dict:
    _, info = _hw()
    return {
        "method": info["method"], "baseline": info["baseline"], "data_source": info["data_source"],
        "latest_date": info["latest_date"], "active_area_km2": info["active_area_km2"],
        "active_share": info["active_share"], "historical_rank_pct": info["active_area_historical_rank_pct"],
        "n_events": len(info["events"]), "ocean_area_km2": info["ocean_area_km2"], "what_is": WHAT_IS, "how_detected": HOW_DETECTED,
        "min_event_cells": info["min_event_cells"],
    }


def list_events(min_category: int = 1, min_area_km2: float = 0.0) -> dict:
    _, info = _hw()
    items = [ev for ev in info["events"] if ev["category"] >= min_category and ev["area_km2"] >= min_area_km2]
    return {"summary": summary(), "total": len(items), "items": items}


def get_event(event_id: str) -> dict | None:
    _, info = _hw()
    for ev in info["events"]:
        if ev["id"] == event_id:
            return {"event": ev, "explanation": explain(ev, info), "summary": summary(),
                    "yearly": info["yearly"], "method": info["method"]}
    return None


def timeseries(days: int) -> dict:
    _, info = _hw()
    d = info["daily"]
    sl = slice(-days, None)
    return {"method": info["method"], "unit_area": "km2", "ocean_area_km2": info["ocean_area_km2"],
            "dates": d["dates"][sl], "heatwave_area_km2": d["heatwave_area_km2"][sl],
            "mean_sst": d["mean_sst"][sl], "mean_anomaly": d["mean_anomaly"][sl],
            "yearly": info["yearly"]}
