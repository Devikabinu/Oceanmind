"""The explanatory layer of the location report: per-factor reading of the risk drivers, the marine-heatwave analysis, how the 7-day forecast reads and why it is warmer or
cooler, which factors dominate the score, and the spatial pattern around the place. Every sentence is built from values already in the report (observed, forecast, heatwave
state) or from the recent series and the surrounding anomaly field read from the dataset; nothing is generic and no physical cause is named, because none of the model's inputs
is a cause."""
from __future__ import annotations

from collections import Counter

import numpy as np
import pandas as pd

from app.services import forecast_reading as fr
from app.services.explain_service import EVIDENCE_KINDS

SPATIAL_HALF_DEG = 5.0


def recent_series(store, date: str, i: int, j: int, n: int = 7) -> list[dict]:
    """SST and anomaly at this cell on the last n days up to `date` (a day without a valid value is left out, never filled)."""
    dates = store.dates
    pos = int(dates.get_loc(pd.Timestamp(date)))
    out = []
    for t in dates[max(0, pos - n + 1):pos + 1]:
        an, _, tt = store.native_layer("anomaly", t)
        sst, _, _ = store.native_layer("sst", t)
        a, s = float(an[i, j]), float(sst[i, j])
        if np.isfinite(a) and np.isfinite(s):
            out.append({"date": str(tt.date()), "anomaly_c": round(a, 2), "sst_c": round(s, 2)})
    return out


recent_anomaly = recent_series          # the name the tests and older callers use


def trends(recent: list[dict]) -> dict | None:
    """3-day and 7-day change of SST (as a slope per day) and of the anomaly over the recent days that have a value."""
    if len(recent) < 3:
        return None

    def slope(rows, key):
        y = [r[key] for r in rows]
        return float(np.polyfit(np.arange(len(y)), y, 1)[0]) if len(y) >= 2 else None
    last3 = recent[-3:]
    return {"days": len(recent), "sst_3d_c_per_day": round(slope(last3, "sst_c"), 3), "sst_7d_c_per_day": round(slope(recent, "sst_c"), 3),
            "anomaly_3d_change_c": round(last3[-1]["anomaly_c"] - last3[0]["anomaly_c"], 2), "anomaly_7d_change_c": round(recent[-1]["anomaly_c"] - recent[0]["anomaly_c"], 2),
            "from": recent[0]["date"], "to": recent[-1]["date"]}


def spatial_pattern(store, date: str, i: int, j: int, anomaly_here: float | None, half_deg: float = SPATIAL_HALF_DEG) -> dict | None:
    """The anomaly field within +-half_deg of the place on the report date: its mean, how much of it is warm or cold, and whether this place is warmer or colder than its surroundings."""
    try:
        vals, _, _ = store.native_layer("anomaly", date)
    except Exception:  # noqa: BLE001 - optional context
        return None
    k = int(round(half_deg / store.res))
    win = vals[max(0, i - k): i + k + 1, max(0, j - k): j + k + 1]
    ok = win[np.isfinite(win)]
    if ok.size < 20:
        return None
    mean = float(ok.mean())
    warm, cold = float((ok >= 0.5).mean()), float((ok <= -0.5).mean())
    label = "a warm-water area" if warm >= 0.6 else "a cold-water area" if cold >= 0.6 else "mixed warm and cold water"
    rel = None
    if anomaly_here is not None:
        rel = "warmer than" if anomaly_here - mean > 0.3 else "colder than" if anomaly_here - mean < -0.3 else "about the same as"
    return {"half_deg": half_deg, "cells": int(ok.size), "mean_anomaly_c": round(mean, 2), "share_warm_pct": round(100 * warm), "share_cold_pct": round(100 * cold), "label": label, "relative_to_surroundings": rel,
            "text": f"Within ±{half_deg:g}° the mean anomaly is {mean:+.1f} °C ({round(100 * warm)}% of {ok.size} ocean cells at least +0.5 °C, {round(100 * cold)}% at most -0.5 °C): {label}"
                    + (f"; this place is {rel} its surroundings." if rel else ".")}


def _signed(v: float) -> str:
    return f"{v:+.1f} °C"


def _hw_trend(recent: list[dict]) -> str | None:
    """strengthening / weakening / persisting for a warm event, from the recent anomaly series (observed)."""
    if len(recent) < 3:
        return None
    d = recent[-1]["anomaly_c"] - recent[0]["anomaly_c"]
    return "strengthening" if d > 0.3 else "weakening" if d < -0.3 else "persisting"


def heatwave_analysis(out: dict, recent: list[dict]) -> dict | None:
    hw = out.get("heatwave") or {}
    if not hw.get("available"):
        return {"active": None, "status": None, "lines": [hw.get("message", "Marine-heatwave status applies to the dataset's latest date only.")], "trend": None, "continuation": None}
    if not hw.get("inside"):
        return {"active": False, "status": None, "lines": ["No active marine heatwave is detected at this location.", "A heatwave needs SST above the seasonal 90th percentile for at least 5 consecutive days; this is a valid result, not missing data."],
                "trend": None, "continuation": None}
    ev, run = hw.get("event"), hw.get("run_days")
    a = (out.get("conditions") or {}).get("anomaly")
    f = out.get("forecast") or {}
    fa = f.get("forecast_anomaly") if f.get("available") else None
    trend = _hw_trend(recent)
    base_years = (hw.get("baseline") or [None, None])
    lines = [f"Current status: a marine heatwave is active at this location. It has persisted for {run} days at this cell" + (f"; the event began {ev['start_date']} and has lasted {ev['duration_days']} days." if ev else ".")]
    if a is not None:
        lines.append(f"The current anomaly is {_signed(a)}" + (f"; the event's maximum anomaly is {_signed(ev['max_anomaly_c'])}" if ev and ev.get("max_anomaly_c") is not None else "") + ".")
    lines.append("Threshold: SST above the seasonal 90th percentile of the " + (f"{base_years[0][:4]}-{base_years[1][:4]} " if base_years[0] else "") + "baseline for at least 5 consecutive days (project definition after Hobday et al., 2016).")
    if ev:
        lines.append(f"Category {ev['category_name']}; cumulative intensity {ev['cumulative_intensity_c_days']:,.0f} °C·days over about {ev['area_km2']:,.0f} km².")
    if trend:
        lines.append(f"Recent anomaly trend: over the last {len(recent)} days the anomaly here went from {_signed(recent[0]['anomaly_c'])} to {_signed(recent[-1]['anomaly_c'])}, so the heatwave is {trend} (observed).")
    status = continuation = None
    frac = ev.get("forecast_still_above_p90_day7") if ev else None
    if fa and a is not None:
        end, low = fa[-1], min(fa) if a >= 0 else max(fa)
        if end < 0.5 or (frac is not None and frac < 0.25):
            status = "Ending"
        elif end > a + 0.3 and (frac is None or frac >= 0.5):
            status = "Strengthening"
        elif end < a - 0.3:
            status = "Weakening"
        else:
            status = "Persisting"
        continuation = {"Ending": "ending", "Strengthening": "strengthening", "Weakening": "weakening", "Persisting": "persistence"}[status]
        stays = "remain above +1.0 °C through day +%d" % len(fa) if low >= 1.0 else f"reach {_signed(end)} by day +{len(fa)}"
        lines.append(f"Forecast relationship: the forecast anomalies at this cell go from {_signed(a)} to {_signed(end)} and {stays}"
                     + (f"; {frac * 100:.0f}% of the event area stays above the heatwave threshold on day 7" if frac is not None else "")
                     + f". Classification: {status} (model prediction, not an observation).")
    lines.append("Environmental significance: heatwaves that last weeks at this intensity are associated with higher thermal stress for temperature-sensitive marine life. This system does not measure biological impact.")
    return {"active": True, "status": status, "lines": lines, "trend": trend, "continuation": continuation}


def _forecast_lines(f: dict, rd: dict) -> list[str]:
    days = ", ".join(f"+{k + 1}d {v:+.1f}" for k, v in enumerate(f["forecast_anomaly"]))
    trend = fr.trend_label(f["forecast_anomaly"])
    return [f"Forecast anomaly by day (°C): {days}.", f"Maximum predicted |anomaly| {rd['max_abs_anomaly_c']:.1f} °C; mean {rd['mean_anomaly_c']:+.1f} °C; the anomaly is {'increasing' if trend == 'rising' else 'decreasing' if trend == 'falling' else 'stable'} across the forecast ({rd['anomaly_label']})."]


def risk_factor_details(out: dict, recent: list[dict], hw_an: dict | None) -> dict:
    """Per driver: a classification and the lines that explain its value. Keys are the driver factor names."""
    conv = out.get("conditions") or {}
    a = conv.get("anomaly")
    f = out.get("forecast") or {}
    sp = out.get("species") or {}
    c = sp.get("counted") or {}
    d: dict = {}
    if a is not None:
        cls = fr.classify_anomaly(a)
        d["anomaly"] = {"classification": cls, "lines": [f"Observed anomaly {_signed(a)}: SST is {abs(a):.1f} °C {'above' if a >= 0 else 'below'} the climatological normal for this day ({conv.get('normal_sst')} °C). Classified {cls}.",
                                                          {"Low": "A departure under 1 °C is within the usual variation.", "Moderate": "A departure of 1 to 2 °C is notable.",
                                                           "High": "A departure of 2 to 3 °C is large for this time of year.", "Extreme": "A departure above 3 °C is extreme; the score factor saturates at 3 °C."}[cls]]}
    if hw_an is not None:
        d["persistence"] = {"classification": ("Active heatwave" if hw_an["active"] else "No active heatwave" if hw_an["active"] is False else "Not computed for this date"), "lines": hw_an["lines"][:4]}
    rd = f.get("reading") if f.get("available") else None
    if rd:
        d["forecast"] = {"classification": fr.classify_anomaly(rd["max_abs_anomaly_c"]), "lines": _forecast_lines(f, rd)}
    groups = Counter(i.get("taxon_group") for i in sp.get("items", []) if i.get("taxon_group"))
    if c.get("observations"):
        where = {"nearby": "nearby", "regional": "regional"}.get(c.get("scope"), "local")
        d["overlap"] = {"classification": f"{where.capitalize()} records" + (" (older)" if c.get("historical") else ""),
                        "lines": [c["label"], f"Spatial range used: about {c['radius_deg']:g}°; time range: {c.get('earliest_record') or 'recent'} to {c.get('latest_record')}.",
                                  ("Groups recorded: " + ", ".join(f"{g} ({n})" for g, n in groups.most_common(5)) + ".") if groups else "Taxonomic groups are not recorded for these species.",
                                  "Why it matters: the score counts how many species have records where these conditions occur, because a thermal anomaly matters ecologically where animals live. "
                                  "Records show observed presence, not range. The score uses the project's stored OBIS selection (distinct species per 2×2° block); the live OBIS summary below adds context and does not change the score."]}
    return d


def why_forecast(out: dict, recent: list[dict], tr: dict | None, spatial: dict | None) -> dict | None:
    f = out.get("forecast") or {}
    rd = f.get("reading")
    if not f.get("available") or not rd:
        return None
    a = (out.get("conditions") or {}).get("anomaly")
    hw = out.get("heatwave") or {}
    word = {"warming": "warmer", "cooling": "cooler", "stable": "about the same"}[rd["label"]]
    bullets: list[dict] = []

    def add(kind, text):
        bullets.append({"kind": kind, "label": EVIDENCE_KINDS[kind], "text": text})

    if len(recent) >= 3:
        r0, r1 = recent[0], recent[-1]
        t = fr.trend_label([r["anomaly_c"] for r in recent])
        add("observed", f"Recent trend: the anomaly here went from {_signed(r0['anomaly_c'])} on {r0['date']} to {_signed(r1['anomaly_c'])} on {r1['date']} ({t}).")
        if tr:
            add("observed", f"SST changed at {tr['sst_3d_c_per_day']:+.2f} °C per day over the last 3 days and {tr['sst_7d_c_per_day']:+.2f} °C per day over the last {tr['days']} days; the anomaly changed by "
                            f"{tr['anomaly_3d_change_c']:+.2f} °C over 3 days and {tr['anomaly_7d_change_c']:+.2f} °C over {tr['days']} days.")
        same = all(r["anomaly_c"] * r1["anomaly_c"] > 0 and abs(r["anomaly_c"]) >= 0.5 for r in recent)
        if same:
            add("observed", f"Persistence: the anomaly kept the same sign and a size of at least 0.5 °C on all {len(recent)} recent days, so the {'warm' if r1['anomaly_c'] > 0 else 'cold'} departure is not a one-day fluctuation.")
    if spatial:
        add("observed", f"Spatial pattern: {spatial['text']}")
    if hw.get("available"):
        add("observed", (f"Heatwave state: this cell has been in a marine heatwave for {hw['run_days']} days." if hw.get("inside") else "Heatwave state: this cell is not in a marine heatwave."))
    add("model_prediction", f"Forecast trajectory: {rd['text']}")
    if a is not None and rd["label"] != "stable":
        add("model_prediction", f"The predicted {'rise' if rd['label'] == 'warming' else 'fall'} of {abs(rd['sst_change_c']):.2f} °C comes with the anomaly {fr.EXPECTED_ING[rd['anomaly_label']]} ({_signed(a)} now, {_signed(rd['anomaly_end_c'])} at day +{rd['days']}).")
    add("physical_cause", "Why the ocean itself is changing (currents, winds, heat exchange, ENSO) cannot be established: none of these is an input of the model. The measured sensitivity of the forecast is in the explanation below.")
    return {"direction": rd["label"], "headline": f"Why is the forecast {word}?", "bullets": bullets}


def risk_dominance(out: dict) -> str | None:
    """Which factors dominate the score, written from the actual contributions."""
    k = out.get("risk") or {}
    drivers = [d for d in k.get("drivers", []) if d.get("available") and d.get("contribution") is not None]
    if not drivers or k.get("score") is None:
        return None
    order = sorted(drivers, key=lambda d: d["contribution"], reverse=True)
    names = {"anomaly": "the SST anomaly", "persistence": "the heatwave duration", "forecast": "the forecast anomaly", "overlap": "species overlap"}
    top = order[0]
    share = lambda d: f"{d['contribution']:.2f} of {k['score']:.2f}"          # noqa: E731
    text = f"The score of {k['score']:.2f} is driven mostly by {names[top['factor']]} ({share(top)})"
    if len(order) > 1 and order[1]["contribution"] >= 0.5 * top["contribution"] and order[1]["contribution"] > 0.02:
        text += f" and {names[order[1]['factor']]} ({share(order[1])})"
    low = [d for d in order if d["contribution"] < 0.02]
    if low:
        text += f"; {', '.join(names[d['factor']] for d in low)} add{'s' if len(low) == 1 else ''} almost nothing"
    fc = next((d for d in drivers if d["factor"] == "forecast"), None)
    rd = (out.get("forecast") or {}).get("reading")
    if fc and rd and fc["contribution"] >= 0.05 and top["factor"] != "forecast":
        text += f". The forecast adds {fc['contribution']:.2f} because the anomaly is predicted to be {fr.EXPECTED_ING[rd['anomaly_label']]}"
    return text + "."


def build(out: dict, store, date: str, i: int, j: int) -> None:
    f = out.get("forecast") or {}
    sst, a = (out.get("conditions") or {}).get("sst"), (out.get("conditions") or {}).get("anomaly")
    if f.get("available") and f.get("forecast_sst") and f.get("forecast_anomaly") and sst is not None and a is not None:
        f["reading"] = fr.reading(sst, a, f["forecast_sst"], f["forecast_anomaly"], f.get("dates"), f.get("typical_error_c"), f.get("climatology"), (out.get("conditions") or {}).get("normal_sst"))
        f["direction_by_day"] = [fr.day_direction(v - sst) for v in f["forecast_sst"]]
        f["change_vs_latest_c"] = [round(v - sst, 2) for v in f["forecast_sst"]]
    try:
        recent = recent_series(store, date, i, j)
    except Exception:  # noqa: BLE001 - the explanation is built without the recent series rather than failing the report
        recent = []
    tr = trends(recent)
    sp = spatial_pattern(store, date, i, j, a)
    hw_an = heatwave_analysis(out, recent)
    if out.get("heatwave") is not None and hw_an is not None:
        out["heatwave"]["analysis"] = hw_an
    out["analysis"] = {"recent_anomaly": recent, "trends": tr, "spatial_pattern": sp, "risk_factors": risk_factor_details(out, recent, hw_an), "why_forecast": why_forecast(out, recent, tr, sp),
                       "risk_dominance": risk_dominance(out)}
    for dr in (out.get("risk") or {}).get("drivers", []):
        extra = out["analysis"]["risk_factors"].get(dr["factor"])
        if extra:
            dr["classification"], dr["detail_lines"] = extra["classification"], extra["lines"]
