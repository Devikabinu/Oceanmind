"""The physical interpretation of one place, written from an evidence package.

  build_package   gathers the REAL values already retrieved (SST, anomaly, trends, heatwave, forecast, winds, radiation, currents, sea level, ENSO, climatology) into one structured package; each
                  measurement gets an id (E1, E2, ...). Nothing is estimated or filled in here.
  narrate         the deterministic narrator: writes the interpretation from the package alone, always available, and the fallback of everything below.
  validate        checks any interpretation (deterministic or AI) against the package: right shape, ids that exist, every number present in the package, no causal verbs, no unmeasured mechanism presented
                  as measured, no damage reported, the confidence level unchanged.
  interpret       the entry point: the narrator's text unless a configured AI provider has produced a validated alternative for exactly this evidence (generated in the background, cached on disk).

Generated text never changes a measurement, the forecast or the risk score: those are returned from the package, not from the text."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.services import ai_providers as aip
from app.services import forecast_reading as fr

log = logging.getLogger("ocean_platform")

SUPPORTS = ("local_measurements", "local_estimate", "climate_context", "climatology", "general_context")
LEVELS = ("low", "moderate", "mixed", "not applicable")
LEVEL_OF = {"moderate (plausible mechanisms)": "moderate", "limited": "low", "mixed": "mixed", "not applicable": "not applicable"}
GENERAL_IDS = ("seasonal_cycle", "persistence", "general_context")
RETRY_AFTER = timedelta(minutes=10)
_inflight: dict[str, threading.Thread] = {}
_failed: dict[str, datetime] = {}
_mutex = threading.Lock()

BANNED = [
    (re.compile(r"\bcaus(?:ed|es|ing)\b", re.I), "a causal verb"),
    (re.compile(r"\b(?:is|are|was|were)\s+(?:largely\s+|mainly\s+|clearly\s+)?(?:driven|forced|produced|triggered) by\b", re.I), "a causal passive"),
    (re.compile(r"\bproves?\b|\bproven\b|\bdefinitely\b|\bcause established\b|\bconfirms? that\b", re.I), "overstated certainty"),
    (re.compile(r"\b(?:winds?|currents?|fluxes|flux|upwelling|heat exchange)\b[^.]{0,40}\bwill\b", re.I), "a prediction of a driver"),
    (re.compile(r"\b(?:will|is going to)\s+(?:continue|persist|strengthen|weaken|keep)\b", re.I), "a certain future claim"),
]
DAMAGE = re.compile(r"\b(?:bleach\w*|mortalit\w*|die-?offs?|dead|killed|collapse\w*|declin\w*|damag\w*)\b", re.I)
NUM = re.compile(r"(?<![\w.])[-+−±]?\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------------------------------------------------------------------------- the package
def _num(x, d=1):
    return None if x is None else round(float(x), d)


def build_package(analysis: dict, ctx: dict, region: str | None = None) -> dict:
    ev: list[dict] = []

    def add(mech, label, value, unit, period, kind):
        eid = f"E{len(ev) + 1}"
        ev.append({"id": eid, "mechanism": mech, "label": label, "value": value, "unit": unit, "period": period, "kind": kind})
        return eid

    a, sst = ctx["anomaly"], ctx["sst"]
    recent = (ctx.get("recent") or [])[-7:]
    tr = ctx.get("trends") or {}
    sst_block = {"date": ctx["date"], "value_c": _num(sst, 2), "normal_c": _num(sst - a, 2), "anomaly_c": _num(a, 2), "class": fr.classify_anomaly(a), "trend_3d_c_per_day": tr.get("sst_3d_c_per_day"),
                 "trend_7d_c_per_day": tr.get("sst_7d_c_per_day"), "anomaly_change_3d_c": tr.get("anomaly_3d_change_c"), "anomaly_change_7d_c": tr.get("anomaly_7d_change_c")}
    if len(recent) >= 5:
        sst_block["sst_change_window_c"] = _num(recent[-1]["sst_c"] - recent[0]["sst_c"], 2)
        sst_block["seasonal_change_window_c"] = _num((recent[-1]["sst_c"] - recent[-1]["anomaly_c"]) - (recent[0]["sst_c"] - recent[0]["anomaly_c"]), 2)
        sst_block["anomaly_change_window_c"] = _num(recent[-1]["anomaly_c"] - recent[0]["anomaly_c"], 2)
        sst_block["window"] = {"start": recent[0]["date"], "end": recent[-1]["date"], "days": len(recent)}
    sst_block["evidence_ids"] = [add("sst", "Sea surface temperature", sst_block["value_c"], "°C", ctx["date"], "measurement (NOAA OISST)"),
                                 add("sst", "SST anomaly", sst_block["anomaly_c"], "°C", ctx["date"], "derived (OISST minus climatology)")]
    hw = ctx.get("heatwave") or {}
    ev_h = hw.get("event") or {}
    hw_block = {"active": hw.get("inside") if hw.get("available") else None, "run_days": hw.get("run_days"), "start_date": ev_h.get("start_date"), "category": ev_h.get("category_name"),
                "max_anomaly_c": ev_h.get("max_anomaly_c"), "status": (hw.get("analysis") or {}).get("status")}
    f = ctx.get("forecast") or {}
    rd = ctx.get("reading")
    fc_block = {"available": bool(rd and f.get("dates")), "issued_from": f.get("issued_from")}
    if fc_block["available"]:
        fc_block.update(days=[{"date": d, "sst_c": _num(s, 2), "anomaly_c": _num(an, 2)} for d, s, an in zip(f["dates"], f["forecast_sst"], f["forecast_anomaly"])], sst_direction=rd["label"], anomaly_trajectory=rd["anomaly_label"],
                        sst_change_c=rd["sst_change_c"], reading_text=rd["text"], typical_error_day7_c=(f.get("typical_error_c") or [None])[-1])
    mechs = []
    for m in analysis["mechanisms"]:
        eids = [add(m["id"], d["label"], d["value"], d["unit"], d["period"], d["kind"]) for d in m["data"] if isinstance(d["value"], (int, float))]
        mechs.append({"id": m["id"], "name": m["name"], "kind": m["kind"], "verdict": m["verdict"], "favours": m["favours"], "quality": m["evidence_quality"], "evidence_ids": eids,
                      "evidence_for": m["evidence_for"], "evidence_against": m["evidence_against"], "caveat": m["caveat"]})
    fam_yes = sorted({pa_family(m["id"]) for m in mechs if m["verdict"] == "consistent" and pa_family(m["id"])})
    fam_no = sorted({pa_family(m["id"]) for m in mechs if m["verdict"] == "not consistent" and pa_family(m["id"])})
    lags = [s["lag_days_behind_sst"] for s in analysis["sources"] if s.get("lag_days_behind_sst") is not None and s["status"] in ("ok", "stale")]
    wb = (ctx.get("winds_baseline_years") or 0)
    pkg = {"version": 1, "location": {"lat": _num(ctx["lat"], 2), "lon": _num(ctx["lon"], 2), "region": region, "resolution": "1° analysis grid cell (point-sampled from 0.25° OISST)"}, "sst": sst_block, "heatwave": hw_block, "forecast": fc_block,
           "mechanisms": mechs, "evidence": ev,
           "dates": analysis["forecast_relationship"]["dates"], "forecast_relationship": analysis["forecast_relationship"]["statements"], "agreement": analysis["forecast_relationship"]["agreement"],
           "confidence": {"level": LEVEL_OF.get(analysis["confidence"]["level"], "low"), "analysis_text": analysis["confidence"]["text"], "families_consistent": fam_yes, "families_conflicting": fam_no,
                          "assessed": sum(1 for m in mechs if m["verdict"] in ("consistent", "not consistent", "inconclusive")), "not_assessable": sum(1 for m in mechs if m["verdict"] == "not assessable"),
                          "max_lag_days": max(lags) if lags else None, "wind_baseline_years": wb},
           "sources": [{"id": s["id"], "label": s["label"], "status": s["status"], "dataset_end": s["dataset_end"], "lag_days": s["lag_days_behind_sst"]} for s in analysis["sources"]]}
    return pkg


def pa_family(mid: str) -> str | None:
    from app.services import physical_analysis as pa
    return pa.FAMILY.get(mid)


# ---------------------------------------------------------------------------------------------------------------------------------------------- validation
def _walk(obj, fn):
    if isinstance(obj, dict):
        for v in obj.values():
            _walk(v, fn)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, fn)
    else:
        fn(obj)


def allowed_numbers(pkg: dict) -> set[str]:
    out: set[str] = {"3.4", "0.25", "1.9", "2.5"}

    def see(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, (int, float)):
            v = abs(float(x))
            out.update({f"{v:.0f}", f"{v:.1f}", f"{v:.2f}", f"{v:.3f}", f"{v * 100:.0f}", f"{v * 100:.1f}", f"{v:g}"})
        elif isinstance(x, str):
            for t in NUM.findall(x):
                out.add(t.lstrip("-+−±"))
    _walk(pkg, see)
    return out


def _strings(o) -> list[str]:
    acc: list[str] = []
    _walk(o, lambda x: acc.append(x) if isinstance(x, str) else None)
    return acc


def _free_number(tok: str) -> bool:
    if "." in tok:
        return False
    n = int(tok)
    return 0 <= n <= 31 or 2000 <= n <= 2035


def validate(out: dict, pkg: dict) -> list[str]:
    """Problems found in an interpretation, an empty list when it is acceptable."""
    errs: list[str] = []
    if not isinstance(out, dict):
        return ["not an object"]

    def text(k, mx):
        v = out.get(k)
        if not isinstance(v, str) or not v.strip() or len(v) > mx:
            errs.append(f"{k} missing or too long")
    text("headline", 220)
    text("summary", 1400)
    ms = out.get("mechanisms")
    if not isinstance(ms, list) or len(ms) > 3:
        errs.append("mechanisms must be a list of at most three")
        ms = []
    mech = {m["id"]: m for m in pkg["mechanisms"]}
    eids = {e["id"] for e in pkg["evidence"]}
    for m in ms:
        if not isinstance(m, dict) or not all(isinstance(m.get(k), str) for k in ("id", "name", "support", "explanation")) or not all(isinstance(m.get(k), list) for k in ("evidence", "evidence_ids", "complications")):
            errs.append("a mechanism has the wrong shape")
            continue
        if m["support"] not in SUPPORTS:
            errs.append(f"unknown support {m['support']!r}")
        if m["id"] not in mech and m["id"] not in GENERAL_IDS:
            errs.append(f"unknown mechanism {m['id']!r}")
        if not set(m["evidence_ids"]) <= eids:
            errs.append(f"{m['id']}: evidence ids that do not exist")
        pm = mech.get(m["id"])
        if m["support"] in ("local_measurements", "local_estimate") and (not pm or pm["verdict"] != "consistent" or not m["evidence_ids"] or not set(m["evidence_ids"]) <= set(pm["evidence_ids"]) or m["id"] == "enso" or (m["support"] == "local_measurements") == (m["id"] == "heat_flux")):
            errs.append(f"{m['id']}: presented as supported by local data without a consistent verdict, its own evidence ids and the right kind (a bulk estimate is never a measurement)")
        if m["support"] == "climate_context" and (not pm or m["id"] != "enso" or pm["verdict"] != "consistent"):
            errs.append(f"{m['id']}: climate context claimed without a consistent ENSO verdict")
        if m["support"] == "general_context" and m["evidence_ids"]:
            errs.append(f"{m['id']}: general context must not cite measurements")
        if pm and pm["verdict"] in ("not assessable", "inconclusive") and m["support"] != "general_context":
            errs.append(f"{m['id']}: an unassessed mechanism presented as supported")
    nt = out.get("near_term")
    if not isinstance(nt, dict) or not isinstance(nt.get("text"), str) or not nt["text"].strip() or len(nt["text"]) > 1000:
        errs.append("near_term missing")
    im = out.get("implications")
    if not isinstance(im, dict) or not all(isinstance(im.get(k), list) for k in ("measured", "general")):
        errs.append("implications missing")
    else:
        for t in im["measured"]:
            if not isinstance(t, str) or DAMAGE.search(t):
                errs.append("a measured implication reports damage or is not text")
    cf = out.get("confidence")
    if not isinstance(cf, dict) or cf.get("level") != pkg["confidence"]["level"] or not isinstance(cf.get("justification"), str) or not cf["justification"].strip():
        errs.append("confidence level changed or justification missing")
    allowed = allowed_numbers(pkg)
    for s in _strings({k: v for k, v in out.items() if k != "provider"}):
        for rx, why in BANNED:
            if rx.search(s):
                errs.append(f"{why}: {rx.search(s).group(0)!r}")
        for tok in NUM.findall(s):
            t = tok.lstrip("-+−±")
            if t not in allowed and not _free_number(t):
                errs.append(f"number {t} is not in the evidence")
        if len(s) > 1500:
            errs.append("a string is too long")
    return list(dict.fromkeys(errs))


# ---------------------------------------------------------------------------------------------------------------------------------------------- the deterministic narrator
RELATION = {
    "wind": {"warm": "Weaker winds mix the surface layer less and evaporate less heat from it, so the surface warms more easily.", "cold": "Stronger winds mix cooler water up from below and evaporate more heat, which favours cooling."},
    "upwelling": {"warm": "Less upwelling-favourable wind brings less cool water to the surface, which favours warm surface water.", "cold": "More upwelling-favourable wind brings more cool water to the surface, which favours cool surface water."},
    "heat_flux": {"warm": "The estimated net heat entering the ocean is above normal (sunshine, cloud, humidity and evaporative loss), which favours warming.", "cold": "The estimated net heat entering the ocean is below normal, which favours cooling."},
    "advection": {"warm": "Ocean currents carry water along the temperature gradient; here the geostrophic flow carries warmer water toward this place, in the direction of the warm anomaly.", "cold": "Ocean currents carry water along the temperature gradient; here the geostrophic flow carries cooler water toward this place, in the direction of the cold anomaly."},
    "sea_level": {"warm": "Higher sea level goes with a deeper layer of warm water, which helps keep the surface warm.", "cold": "Lower sea level goes with a shallower warm layer, which helps keep the surface cool."},
    "enso": {"warm": "El Niño shifts the winds and the depth of warm water across the tropical Pacific and is associated with warm surface anomalies in this region.", "cold": "La Niña shifts the winds and the depth of warm water across the tropical Pacific and is associated with cool surface anomalies in this region."},
}
SHORT = {"wind": ("weaker winds", "stronger winds"), "upwelling": ("reduced upwelling", "enhanced upwelling"), "heat_flux": ("air–sea heat exchange",) * 2, "advection": ("ocean currents",) * 2,
         "sea_level": ("a deep warm layer", "a shallow warm layer"), "enso": ("ENSO",) * 2}


def _support_kind(mid: str) -> str:
    return "climate_context" if mid == "enso" else "local_estimate" if mid == "heat_flux" else "local_measurements"


def _rank(m: dict) -> tuple:
    return (m["quality"] == "moderate", m["quality"] == "low", m["id"] != "enso")


def narrate(pkg: dict) -> dict:
    s, hw, fc, cf = pkg["sst"], pkg["heatwave"], pkg["forecast"], pkg["confidence"]
    a = s["anomaly_c"]
    side = "warm" if a > 0 else "cold"
    ms = {m["id"]: m for m in pkg["mechanisms"]}
    consistent = sorted([m for m in pkg["mechanisms"] if m["verdict"] == "consistent"], key=_rank, reverse=True)
    conflicts = [m for m in pkg["mechanisms"] if m["verdict"] == "not consistent"]
    sst_ch, seas, an_ch = s.get("sst_change_window_c"), s.get("seasonal_change_window_c"), s.get("anomaly_change_window_c")
    seasonal_story = sst_ch is not None and seas is not None and abs(sst_ch) >= 0.3 and sst_ch * seas > 0 and abs(seas) >= 0.6 * abs(sst_ch)
    big = abs(a) >= 0.5

    # --- headline and summary --------------------------------------------------------------------------------------------------
    if big:
        head = f"{abs(a):.1f} °C {'above' if a > 0 else 'below'} normal"
        if hw.get("active"):
            head += f", inside a marine heatwave that has lasted {hw['run_days']} days at this cell"
        head += ", steady over the last 3 days" if (not hw.get("active") and s.get("anomaly_change_3d_c") is not None and abs(s["anomaly_change_3d_c"]) < 0.3) else ""
    elif seasonal_story:
        head = f"Near-normal temperature: the {'cooling' if sst_ch < 0 else 'warming'} of {abs(sst_ch):.1f} °C is the normal seasonal cycle"
    else:
        head = "Near-normal temperature with no unusual signal"
    rel = "at" if abs(a) < 0.05 else f"{abs(a):.1f} °C {'above' if a > 0 else 'below'}"
    parts = [f"Sea surface temperature is {s['value_c']:.1f} °C on {s['date']}, {rel} the {s['normal_c']:.1f} °C normal for the date ({str(s['class']).lower()} anomaly)."]
    if sst_ch is not None:
        w = s["window"]["days"]
        if seasonal_story:
            parts.append(f"Over the past {w} days SST {'fell' if sst_ch < 0 else 'rose'} by {abs(sst_ch):.1f} °C, but the normal seasonal cycle accounts for {abs(seas):.1f} °C of that and the anomaly changed by only {an_ch:+.1f} °C: "
                         f"this is seasonal {'cooling' if sst_ch < 0 else 'warming'}, not an anomalous event.")
        else:
            parts.append(f"Over the past {w} days SST changed by {sst_ch:+.1f} °C (the normal seasonal change is {seas:+.1f} °C) and the anomaly by {an_ch:+.1f} °C, so the {side + ' anomaly is ' if big else 'anomaly remains near normal'}"
                         f"{'strengthening' if big and an_ch * (1 if a > 0 else -1) > 0.3 else 'weakening' if big and an_ch * (1 if a > 0 else -1) < -0.3 else 'holding steady' if big else ''}.")
    if hw.get("active"):
        parts.append(f"A marine heatwave is active here{', started ' + hw['start_date'] if hw.get('start_date') else ''}{' (' + str(hw['category']) + ')' if hw.get('category') else ''}.")
    elif hw.get("active") is False and big:
        parts.append("No marine heatwave is active at this cell.")
    if big and consistent:
        parts.append("The measurements most consistent with this are " + ", ".join(SHORT[m["id"]][a < 0] for m in consistent[:3]) + ".")
    elif big:
        parts.append("None of the local measurements clearly accounts for this anomaly, so what follows separates what is measured from general context.")

    # --- mechanisms ----------------------------------------------------------------------------------------------------------------
    mechs: list[dict] = []
    for m in consistent[:3]:
        comp = list(m["evidence_against"])
        comp += [f"{o['name'].split(' (')[0]} points the other way: {o['evidence_against'][0]}" for o in conflicts if o["id"] != m["id"] and o["evidence_against"]][:2]
        mechs.append({"id": m["id"], "name": m["name"], "support": _support_kind(m["id"]), "explanation": RELATION[m["id"]][side], "evidence": list(m["evidence_for"]), "evidence_ids": list(m["evidence_ids"]),
                      "complications": comp + ([m["caveat"]] if m["caveat"] else [])})
    if seasonal_story and len(mechs) < 3:
        mechs.append({"id": "seasonal_cycle", "name": "Seasonal cycle", "support": "climatology",
                      "explanation": f"The normal temperature for the date itself {'falls' if seas < 0 else 'rises'} at this time of year, so a change in SST of this size is expected without any anomaly.",
                      "evidence": [f"The climatological SST changed by {seas:+.1f} °C over the same {s['window']['days']} days while the observed SST changed by {sst_ch:+.1f} °C."], "evidence_ids": [], "complications": []})
    if big and not mechs:
        mechs.append({"id": "persistence", "name": "Persistence of an existing anomaly", "support": "general_context",
                      "explanation": "Upper-ocean temperature anomalies change slowly, so an anomaly of this size usually persists for weeks once established. This is general scientific context: the local measurements here do not identify what started or maintains it.",
                      "evidence": [], "evidence_ids": [], "complications": [m["evidence_against"][0] for m in conflicts if m["evidence_against"]][:2]})
    if big and conflicts and not consistent:
        pass

    # --- near term ------------------------------------------------------------------------------------------------------------
    if fc["available"]:
        nt = fc["reading_text"]
        if hw.get("status"):
            nt += f" The heatwave is classified as {str(hw['status']).lower()} on the forecast."
        rel = [t for t in pkg["forecast_relationship"] if t.startswith("The indicators") or t.startswith("None of the measured")]
        nt += (" " + rel[0]) if rel else ""
        nt += " Wind, current and radiation values are the latest observations, not forecasts, so how they evolve over the week is not known here."
    else:
        nt = "No forecast is available for this place and date."

    # --- implications --------------------------------------------------------------------------------------------------------
    measured, general = [], []
    measured.append(f"SST is {'at' if abs(a) < 0.05 else str(round(abs(a), 1)) + ' °C ' + ('above' if a > 0 else 'below')} the normal for the date (observed, NOAA OISST).")
    if hw.get("active"):
        measured.append(f"This cell has been in marine-heatwave conditions for {hw['run_days']} days" + (f", starting {hw['start_date']}" if hw.get("start_date") else "") + " (derived from the SST record).")
    if big and a > 0:
        general += ["Sustained above-normal temperature may increase thermal stress in temperature-sensitive organisms and can reduce habitat suitability for some species.",
                    "A long-lasting marine heatwave can compound that stress and may shift where some species are found." if (hw.get("active") and (hw.get("run_days") or 0) >= 14) else "If it persists, conditions could become a marine heatwave."]
    elif big:
        general += ["Water this much cooler than normal may stress species adapted to warmer water and can shift where some species are found.", "Cooler surface water can also change mixing and nutrient supply."]
    else:
        general += ["A near-normal temperature carries no unusual thermal signal for marine life at this place and time."]
    if big:
        general.append("Effects on plankton, fisheries or spawning depend on the species and season at this place and can only be judged with biological data, which this analysis does not include.")

    # --- confidence --------------------------------------------------------------------------------------------------------
    yes, no = cf["families_consistent"], cf["families_conflicting"]
    crit = [{"text": f"Independent lines of evidence consistent with the anomaly: {len(yes)}" + (f" ({', '.join(yes)})" if yes else ""), "met": len(yes) >= 2},
            {"text": "No assessed indicator contradicts the anomaly" if not no else f"Indicators that contradict it: {', '.join(no)}", "met": not no},
            {"text": "Driver observations are within three days of the SST observation" + (f" (largest lag {cf['max_lag_days']} days)" if cf["max_lag_days"] is not None else ""), "met": cf["max_lag_days"] is not None and cf["max_lag_days"] <= 3},
            {"text": f"Mechanisms that could be assessed: {cf['assessed']} of {cf['assessed'] + cf['not_assessable']}", "met": cf["assessed"] >= 4}]
    return {"headline": head[:220], "summary": " ".join(parts), "mechanisms": mechs, "near_term": {"text": nt}, "implications": {"measured": measured, "general": general},
            "confidence": {"level": cf["level"], "justification": cf["analysis_text"], "criteria": crit}}


# ---------------------------------------------------------------------------------------------------------------------------------------------- key measurements for the first view
def key_measurements(pkg: dict) -> list[dict]:
    want = ["SST anomaly", "Departure of wind speed", "Net surface heat-flux anomaly", "Sea level anomaly, 7-day mean", "Niño 3.4", "Oceanic Niño Index"]
    out = [{"label": "SST anomaly", "value": pkg["sst"]["anomaly_c"], "unit": "°C", "period": pkg["sst"]["date"], "kind": "derived (OISST minus climatology)"}]
    for w in want[1:]:
        e = next((x for x in pkg["evidence"] if x["label"].startswith(w)), None)
        if e:
            out.append({k: e[k] for k in ("label", "value", "unit", "period", "kind")})
    if pkg["heatwave"].get("active"):
        out.append({"label": "Marine-heatwave run at this cell", "value": pkg["heatwave"]["run_days"], "unit": "days", "period": pkg["sst"]["date"], "kind": "derived (SST record)"})
    return out[:6]


# ---------------------------------------------------------------------------------------------------------------------------------------------- orchestration
def _cache_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "cache" / "physical_ai"


def _digest(provider_name: str, pkg: dict) -> str:
    return hashlib.sha256((provider_name + aip.PROMPT_VERSION + json.dumps(pkg, sort_keys=True, default=str)).encode()).hexdigest()[:32]


def _load(key: str) -> dict | None:
    try:
        return json.loads((_cache_dir() / f"{key}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(key: str, obj: dict) -> None:
    d = _cache_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f"{key}.tmp"
    tmp.write_text(json.dumps(obj), encoding="utf-8")
    tmp.replace(d / f"{key}.json")


def parse_json(text: str) -> dict:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("no JSON object")
    return json.loads(t[i:j + 1])


def _generate(key: str, provider, pkg: dict) -> None:
    try:
        raw = provider.generate(aip.SYSTEM_PROMPT, aip.user_message(pkg), get_settings().AI_TIMEOUT_S)
        out = parse_json(raw)
        problems = validate(out, pkg)
        if problems:
            raise ValueError("failed validation: " + "; ".join(problems[:4]))
        _save(key, {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "provider": provider.name, "output": out})
        _failed.pop(key, None)
    except Exception as exc:  # noqa: BLE001 - any failure leaves the deterministic text in place
        _failed[key] = datetime.now(timezone.utc)
        _failed[key + "!why"] = str(exc)[:200]                                   # type: ignore[assignment]
        log.warning("AI interpretation failed: %s", exc)
    finally:
        with _mutex:
            _inflight.pop(key, None)


def interpret(pkg: dict, wait_s: float = 3.0) -> dict:
    """The interpretation to show: always the deterministic narrator's, replaced by a validated AI text for exactly this evidence when a provider is configured and has produced one."""
    det = narrate(pkg)
    assert not validate(det, pkg), validate(det, pkg)                              # the narrator is held to its own rules
    base = {"key_measurements": key_measurements(pkg), "provider": {"name": "Deterministic evidence narrator", "ai_generated": False, "status": "not_configured",
                                                                      "note": "No AI provider is configured, so the interpretation is written directly from the measurements by a rule-based narrator."}}
    provider = aip.get_provider()
    if provider is None:
        return {**det, **base}
    key = _digest(provider.name, pkg)
    cached = _load(key)
    if cached and not validate(cached["output"], pkg):
        out = {**cached["output"], "confidence": {**cached["output"]["confidence"], "criteria": det["confidence"]["criteria"]}}
        return {**out, **base, "provider": {"name": provider.name, "ai_generated": True, "status": "ok", "generated_at": cached["generated_at"],
                                             "note": "Wording written by an AI model from the evidence package and checked against it; measurements, forecast and confidence level are unchanged."}}
    failed = _failed.get(key)
    if failed and datetime.now(timezone.utc) - failed < RETRY_AFTER:
        return {**det, **base, "provider": {"name": provider.name, "ai_generated": False, "status": "fallback", "note": "The AI provider could not produce a checked interpretation just now; the evidence-based summary is shown."}}
    with _mutex:
        th = _inflight.get(key)
        if th is None:
            th = threading.Thread(target=_generate, args=(key, provider, pkg), daemon=True, name=f"ai-{key[:8]}")
            _inflight[key] = th
            th.start()
    th.join(wait_s)
    cached = _load(key)
    if cached and not th.is_alive() and not validate(cached["output"], pkg):
        return interpret(pkg, 0.0)
    status = "generating" if th.is_alive() else "fallback"
    note = "An AI model is writing the wording from the evidence; the evidence-based summary is shown meanwhile." if status == "generating" else "The AI provider could not produce a checked interpretation; the evidence-based summary is shown."
    return {**det, **base, "provider": {"name": provider.name, "ai_generated": False, "status": status, "note": note}}


def clear_state() -> None:
    _inflight.clear()
    _failed.clear()
