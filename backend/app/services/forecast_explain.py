"""Explaining a forecast: what the model was given, what it predicts, how it is built and how the prediction responds to its input.

Three layers, never mixed:
  * observed / processed data: the input window, climatology and anomaly the model actually received (read from the processed dataset);
  * model prediction: the values the trained ConvLSTM produces;
  * model explanation: a SENSITIVITY analysis, computed by running the real trained network on perturbed copies of its own input (oceanmind_model/explain.py). It tells what
    the network responds to. It is not a physical explanation: ocean currents, winds, ENSO, upwelling or atmospheric forcing are not inputs of the model and are never claimed.
The API itself does not import PyTorch: the sensitivity run is a subprocess of the project's own CLI, cached per place and forecast date."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

from app.services import environment_store as es
from app.services import forecast_reading as fr
from app.services import forecast_store
from app.services.environment import OutputsUnavailable
from app.services.explain_service import EVIDENCE_KINDS

ROOT = Path(__file__).resolve().parents[3]
CONFIG = {"pacific": "config.pacific.yaml"}
TIMEOUT_S = 300
FLAT = 0.05                                    # degC: a change smaller than this is called "about the same"
_cache: dict = {}

CONVLSTM_TEXT = [
    "A convolutional layer looks at small neighbourhoods of a temperature map, so the network sees spatial patterns (fronts, warm or cool patches) instead of independent grid cells.",
    "An LSTM keeps a memory that is updated one time step at a time, so the network follows how those patterns change from day to day.",
    "A ConvLSTM combines the two: every gate of the LSTM is a convolution, so the memory is itself a map and it evolves through the sequence of input maps.",
    "The forecast is produced by the trained network from the sequence of previous SST maps. It is not a manually calculated temperature change, and no physical equation is solved.",
]


def _without_paths(msg: str) -> str:
    """An error that goes to the browser names a missing file by its name only, never by its location on the server (a quoted path may contain spaces)."""
    sep = r'[\\/]'                                                      # a backslash or a slash
    msg = re.sub(r'([\'"])([^\'"]*' + sep + r'[^\'"]*)\1', lambda m: m.group(1) + re.split(sep + '+', m.group(2))[-1] + m.group(1), msg)
    return re.sub(r'(?:[A-Za-z]:)?(?:' + sep + r'+[^\\/\s]+)+' + sep + r'+([^\\/\s]+)', r'\1', msg)


def run_sensitivity(dataset: str, lat: float, lon: float) -> dict:
    """Run the trained model on perturbed copies of the latest input window (a subprocess: the API never imports PyTorch)."""
    cmd = [sys.executable, "-m", "oceanmind_model", "explain", "--config", CONFIG[dataset], "--lat", str(lat), "--lon", str(lon)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["the sensitivity run failed"]
        if "land cell" in tail[0]:
            raise ValueError("This location is land: there is no forecast to explain.")
        raise RuntimeError(_without_paths(tail[0])[:300])
    return json.loads(r.stdout[r.stdout.index("{"):])


def model_info(dataset: str | None) -> dict:
    """What the forecast model is, what it was trained on and how it was tested: all read from the processed dataset's own files."""
    store = es.get_store(dataset)
    ds = store.ref.id
    snap, info, metrics, origin = forecast_store.load(ds)
    d = store.ref.path
    meta = store.meta
    stats = json.loads((d / "stats.json").read_text())
    lookback = int(meta["lookback_days"])
    target = meta["target_channel"]
    splits = {k: {"start": v["start"], "end": v["end"], "days": v["days"]} for k, v in meta["splits"].items()}
    trained_on = (origin or {}).get("trained_on")
    declared = (origin or {}).get("normalization_stats")
    base = metrics["baselines"] if metrics else None
    perf = None
    if base:
        c, p, cl = base["convlstm"], base["persistence"], base["climatology"]
        perf = {"split": metrics["split"], "date_range": metrics["date_range"], "n_windows": metrics["n_windows"], "horizons": metrics["horizons"], "mae": {"convlstm": c["mae"], "persistence": p["mae"], "climatology": cl["mae"]},
                "mean_mae": {"convlstm": c["mean_mae"], "persistence": p["mean_mae"], "climatology": cl["mean_mae"]}, "mae_skill_vs_persistence": c["mae_skill_vs_persistence"],
                "beats_persistence": all(x > 0 for x in c["mae_skill_vs_persistence"])}
    return {
        "dataset": ds, "name": info["model"], "checkpoint": info["checkpoint"], "architecture": info.get("model_cfg"), "architecture_text": CONVLSTM_TEXT,
        "input": {"window_days": lookback, "channels": meta["forecast_channels"], "grid": {"rows": len(meta["lat"]), "cols": len(meta["lon"]), "resolution_deg": meta.get("resolution")}, "description": f"The previous {lookback} daily maps ({', '.join(meta['forecast_channels'])}) on the {len(meta['lat'])}×{len(meta['lon'])} grid.",
                  "not_inputs": "Ocean currents, winds, ENSO or other climate indices, upwelling, salinity, chlorophyll and atmospheric forcing are not inputs of this model."},
        "output": {"variable": f"{target} (sea surface temperature, °C)", "horizons": meta["horizons"], "form": "the model predicts the change from the last observed SST map (residual form), one map per forecast day"},
        "normalisation": {"method": "each channel is z-scored: (value − mean) / std", "dataset_statistics": {k: {"mean": round(v["mean"], 3), "std": round(v["std"], 3)} for k, v in stats["channels"].items() if k in ("sst", "sst_anom", "sst_grad")},
                          "statistics_period": stats.get("train_period"),
                          "applied": ("The dataset is converted to the scale the weights were trained with before the model runs, and the output is converted back" if declared else "The dataset's own statistics are used")},
        "training": {"trained_on": trained_on or "this dataset", "retrained_for_this_dataset": bool(origin and origin.get("retrained")), "note": (origin or {}).get("note")},
        "periods": {"dataset_training": splits.get("train"), "validation": splits.get("val"), "test": splits.get("test")},
        "evaluation": perf, "kinds": EVIDENCE_KINDS,
    }


def _locate(store: es.EnvironmentalStore, lat: float, lon: float) -> tuple[int, int]:
    import math
    if not (math.isfinite(lat) and -90 <= lat <= 90) or not (math.isfinite(lon) and -360 <= lon <= 360):
        raise ValueError("lat must be between -90 and 90 and lon between -360 and 360")
    ext = store.extent
    a = es._axis_lon(store, lon)
    if not (ext["lat_min"] <= lat <= ext["lat_max"] and a <= ext["lon_max"]):
        raise ValueError("This location is outside the dataset: there is no forecast to explain.")
    i = min(int(math.floor((lat - ext["lat_min"]) / store.res)), len(store.lat) - 1)
    j = min(int(math.floor((a - ext["lon_min"]) / store.res)), len(store.lon) - 1)
    if bool(store.land[i, j]):
        raise ValueError("This location is land: there is no forecast to explain.")
    return i, j


def _dir(change: float) -> str:
    return "about the same" if abs(change) < FLAT else "warmer" if change > 0 else "cooler"


def explain(dataset: str | None, lat: float, lon: float, runner=None) -> dict:
    store = es.get_store(dataset)
    ds = store.ref.id
    if ds not in CONFIG:
        return {"available": False, "dataset": ds, "message": "The forecast of this dataset is explained on the NE Pacific forecast page; per-location sensitivity is available for the Pacific dataset."}
    i, j = _locate(store, lat, lon)
    try:
        snap, info, metrics, origin = forecast_store.load(ds)
    except OutputsUnavailable as exc:
        return {"available": False, "dataset": ds, "message": str(exc)}
    issued = info["latest"]["observed_date"]
    latest = str(store.dates[-1].date())
    info_m = model_info(ds)
    base = {"dataset": ds, "model": info_m, "issued_from": issued, "latest_observation": latest, "cell": {"row": i, "col": j, "lat": float(store.lat[i]), "lon": float(store.lon[j])}}
    if issued != latest:
        return {**base, "available": False, "message": f"The forecast was issued from {issued} but the newest observation is {latest}; it is not explained as if it were current. Run the refresh to regenerate it."}
    key = (ds, issued, i, j, (store.ref.path / "model" / "dashboard" / "snapshot.npz").stat().st_mtime)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = (runner or run_sensitivity)(ds, float(store.lat[i]), float(store.lon[j]))
    sens = _cache[key]
    w = sens["input_window"]
    sst, clim, anom = w["sst_c"], w["climatology_c"], w["anomaly_c"]
    last = sst[-1]
    fc = np.asarray(sens["forecast_c"], dtype=float)
    published = snap["latest_forecast"][:, i, j]
    clim_t = snap["latest_climatology"][:, i, j]
    mae = metrics["baselines"]["convlstm"]["mae"] if metrics else None
    slope = float(np.polyfit(np.arange(len(sst)), sst, 1)[0])
    rel = "warmer" if anom[-1] > 0.5 else "cooler" if anom[-1] < -0.5 else "close to normal"
    current = {
        "date": w["dates"][-1], "sst_c": round(last, 2), "climatological_sst_c": round(clim[-1], 2), "anomaly_c": round(anom[-1], 2), "relation": rel,
        "recent_trend_c_per_day": round(slope, 3), "trend_3d_c_per_day": round(float(np.polyfit(np.arange(3), sst[-3:], 1)[0]), 3), "anomaly_change_3d_c": round(anom[-1] - anom[-3], 2), "anomaly_change_7d_c": round(anom[-1] - anom[0], 2), "recent_change_c": round(sst[-1] - sst[0], 2), "window": [{"date": d, "sst_c": round(a, 2), "climatology_c": round(b, 2), "anomaly_c": round(c, 2)} for d, a, b, c in zip(w["dates"], sst, clim, anom)],
        "statement": (f"Current SST is {last:.1f} °C, approximately {abs(anom[-1]):.1f} °C {'above' if anom[-1] >= 0 else 'below'} the climatological value ({clim[-1]:.1f} °C) for this location and day; "
                      f"it is {rel} than normal." if rel != "close to normal" else f"Current SST is {last:.1f} °C, {anom[-1]:+.1f} °C from the climatological value ({clim[-1]:.1f} °C): close to normal."),
        "trend_statement": f"Over the {len(sst)} days the model was given, SST changed by {sst[-1] - sst[0]:+.2f} °C ({slope:+.3f} °C per day) and the anomaly by {anom[-1] - anom[0]:+.2f} °C.",
        "kind": "observed",
    }
    rows = []
    for h, date in enumerate(info["latest"]["target_dates"]):
        ch = float(published[h] - last)
        rows.append({"day": h + 1, "date": date, "sst_c": round(float(published[h]), 2), "anomaly_c": round(float(published[h] - clim_t[h]), 2), "change_vs_latest_c": round(ch, 2), "direction": _dir(ch),
                     "typical_error_c": None if mae is None else round(float(mae[h]), 2),
                     "statement": f"+{h + 1} day{'s' if h else ''} ({date}): SST is forecast to be {published[h]:.1f} °C, {abs(ch):.2f} °C {'higher' if ch > 0 else 'lower'} than the latest observation "
                                  f"({_dir(ch)}), {published[h] - clim_t[h]:+.1f} °C from normal" + (f"; typical error ±{mae[h]:.2f} °C." if mae is not None else ".")})
    pub_anom = [float(published[h] - clim_t[h]) for h in range(len(published))]
    rd = fr.reading(float(last), float(anom[-1]), [float(x) for x in published], pub_anom, None, None if mae is None else [float(x) for x in mae], [float(x) for x in clim_t], float(clim[-1]))
    s = sens["sensitivity"]
    td, last_day = s["temporal"]["delta_c"], len(s["temporal"]["days"]) - 1
    h7 = len(rows) - 1
    per_day = [row[h7] for row in td]
    top_day = int(np.argmax(np.abs(per_day)))
    local, everywhere = s["local_all_days_c"][h7], s["everywhere_all_days_c"][h7]
    sp = np.array([[np.nan if v is None else v for v in r] for r in s["spatial"]["delta_c"][h7]], dtype=float)
    own = s["spatial"]["own_block"]
    flat_idx = np.unravel_index(np.nanargmax(np.abs(sp)), sp.shape) if np.isfinite(sp).any() else None
    expl = []

    def add(kind, text):
        expl.append({"kind": kind, "label": EVIDENCE_KINDS[kind], "text": text})

    add("model_prediction", f"At day +{h7 + 1} the ConvLSTM predicts {published[h7]:.1f} °C, {rows[h7]['change_vs_latest_c']:+.2f} °C relative to the latest observation, i.e. {rows[h7]['anomaly_c']:+.1f} °C from normal "
                            f"(now {anom[-1]:+.1f} °C).")
    c_top, a_top = per_day[top_day], anom[top_day]
    others = ", ".join(f"{v:+.2f}" for k, v in enumerate(per_day) if k != top_day)
    add("model_explanation", f"Which input day matters most: the observed {'warm' if a_top > 0 else 'cold'} anomaly of {a_top:+.1f} °C on {s['temporal']['days'][top_day]} contributes {c_top:+.2f} °C to the day +{h7 + 1} prediction"
                             + (" (the newest input day)" if top_day == last_day else "") + f". Replacing it with normal conditions would {'lower' if c_top > 0 else 'raise'} the predicted temperature by {abs(c_top):.2f} °C"
                             + (", indicating that the model relies on this recent anomaly when producing the forecast." if abs(c_top) >= FLAT else ", so the model barely responds to this day.") + f" The other input days contribute {others} °C.")
    seasonal = float(clim_t[h7] - clim[-1])
    add("observed", f"Seasonal signal: the normal (climatological) SST at this place changes by {seasonal:+.2f} °C between {w['dates'][-1]} and {info['latest']['target_dates'][h7]}, so part of any warming or cooling is the usual seasonal cycle.")
    a7 = float(published[h7] - clim_t[h7])
    add("model_prediction", f"Anomaly persistence: the anomaly goes from {anom[-1]:+.1f} °C now to {a7:+.1f} °C at day +{h7 + 1} ("
                            + ("it persists" if abs(a7 - anom[-1]) < 0.3 else "it weakens" if abs(a7) < abs(anom[-1]) else "it grows") + "); the recent trend over the input window was "
                            f"{slope:+.3f} °C per day.")
    add("model_explanation", f"Local or distant: the observed anomaly within ±{s['neighbourhood_deg']:g}° of this place contributes {local:+.2f} °C to the day +{h7 + 1} forecast; the anomaly everywhere contributes {everywhere:+.2f} °C.")
    if own is not None and np.isfinite(sp[own[0], own[1]]):
        add("model_explanation", f"Spatial context: the {s['block_deg']:g}°×{s['block_deg']:g}° block containing this place contributes {sp[own[0], own[1]]:+.2f} °C to the day +{h7 + 1} forecast"
                                 + (f"; the block with the largest effect is at ({s['spatial']['lat_edges'][flat_idx[0]]:.0f}°, {s['spatial']['lon_edges'][flat_idx[1]]:.0f}°E) with {sp[flat_idx]:+.2f} °C." if flat_idx is not None else "."))
    cf_h = h7
    base_sst = float(published[cf_h])
    cf_rows = [("Model output with the observed input", 0.0, "The trained ConvLSTM run on the real input window.")]
    cf_rows += [(f"Anomaly of {s['temporal']['days'][top_day]} removed (replaced by normal conditions)", float(per_day[top_day]), "Only the input day with the largest effect is changed."),
                (f"Anomaly within ±{s['neighbourhood_deg']:g}° removed on all input days", float(local), "The local anomaly is replaced by normal conditions on every input day."),
                ("Anomaly removed everywhere on all input days", float(everywhere), "The whole input is replaced by normal conditions.")]
    counterfactual = {"horizon": cf_h + 1, "title": "Model sensitivity: not causal attribution", "date": info["latest"]["target_dates"][cf_h],
                      "rows": [{"label": lab, "sst_c": round(base_sst - c, 2), "anomaly_c": round(base_sst - c - float(clim_t[cf_h]), 2), "difference_c": round(-c, 2), "note": note} for lab, c, note in cf_rows],
                      "reading": (f"Removing the observed {'warm' if a_top > 0 else 'cold'} anomaly of the newest input day from the input sequence would {'reduce' if c_top > 0 else 'raise'} the day +{cf_h + 1} predicted anomaly by "
                                  f"{abs(c_top):.2f} °C (from {base_sst - float(clim_t[cf_h]):+.2f} °C to {base_sst - c_top - float(clim_t[cf_h]):+.2f} °C). The model prediction is sensitive to the recent anomaly pattern; "
                                  "this is a property of the trained model, not evidence that the anomaly caused the future temperature.") if abs(c_top) >= 0.05 else
                                 f"Removing the observed anomaly of the newest input day changes the day +{cf_h + 1} predicted anomaly by only {abs(c_top):.2f} °C: the model prediction is not sensitive to that day."}
    add("model_explanation", "Because the network predicts the change from the last observed map, much of the forecast at a place is the latest observed temperature carried forward; the learned part adds a correction "
                             f"({published[h7] - last:+.2f} °C by day +{h7 + 1}) based on the spatial-temporal patterns it learned in training.")
    add("statistical", f"The model's typical error on this dataset's test period is ±{mae[h7]:.2f} °C at day +{h7 + 1}; differences smaller than that are not meaningful." if mae is not None else "The model has not been evaluated on this dataset.")
    add("possible_explanation", "Seasonal heating or cooling, ocean currents, winds and air-sea heat exchange are plausible physical contributors to any temperature change. None of them is an input of this model, so none was tested here.")
    add("physical_cause", "Not established: this analysis cannot say whether ocean currents, winds, ENSO, upwelling or atmospheric forcing drive the predicted change. Model sensitivity is not physical causation.")
    same_sign = all(x * anom[-1] > 0 for x in anom) and abs(anom[-1]) >= 0.5
    start_a, end_a = float(anom[-1]), pub_anom[-1]
    if rd["anomaly_label"] == "changing sign":
        a_move = f"The forecast changes from a {'positive' if start_a > 0 else 'negative'} to a {'positive' if end_a > 0 else 'negative'} anomaly during the forecast period ({start_a:+.1f} °C to {end_a:+.1f} °C)."
    else:
        a_move = f"The forecast anomaly {'increases' if end_a > start_a else 'decreases'} from {start_a:+.1f} °C to {end_a:+.1f} °C (total change {end_a - start_a:+.1f} °C)."
    in_change = float(sst[-1] - sst[0])
    in_dir = "rising" if in_change > fr.STABLE_C else "falling" if in_change < -fr.STABLE_C else "about level"
    seasonal_c = rd.get("seasonal_change_c")
    near_season = seasonal_c is not None and abs(rd["sst_change_c"] - seasonal_c) < fr.SEASON_MATCH_C
    window = f"SST {sst[0]:.1f} to {sst[-1]:.1f} °C, anomaly {anom[0]:+.1f} to {anom[-1]:+.1f} °C over the {len(sst)} input days"
    agree = (rd["label"] == "warming" and in_dir == "rising") or (rd["label"] == "cooling" and in_dir == "falling")
    if rd["label"] == "stable":
        why = f"The model predicts little change in SST ({fr.sg(rd['sst_change_c'])} °C over {rd['days']} days); the input window shows {window}."
    elif agree:
        why = (f"The recent input sequence shows {in_dir} SST ({window}), and the model projects that {'warming' if rd['label'] == 'warming' else 'cooling'} tendency forward"
               + (" with the anomaly persisting across the window" if same_sign else "") + (f"; the predicted change is close to the normal seasonal change of {fr.sg(seasonal_c)} °C" if near_season else "") + ".")
    else:
        why = (f"The recent input sequence shows {in_dir} SST ({window}), but the model predicts {'warming' if rd['label'] == 'warming' else 'cooling'}, so the forecast does not simply continue the recent tendency"
               + (f"; the predicted change is close to the normal seasonal change of {fr.sg(seasonal_c)} °C, so it follows the usual seasonal cycle while the anomaly {fr.EXPECTED_ING[rd['anomaly_label']]}" if near_season else
                  "; the sensitivity analysis below shows which parts of the input the prediction depends on") + ".")
    interpretation = {"direction": rd["label"], "anomaly_trajectory": rd["anomaly_label"], "start_anomaly_c": round(start_a, 2), "end_anomaly_c": round(end_a, 2), "total_change_c": round(end_a - start_a, 2),
                      "sst_change_c": rd["sst_change_c"], "text": f"{rd['text']} {why} {a_move} This is a model interpretation, not proof of physical causation."}
    # ---- the measured sensitivity signals, ranked; the plain-language reading; the inputs actually given to the model ----------------------------------------------------------
    days_in = s["temporal"]["days"]
    own_val = float(sp[own[0], own[1]]) if own is not None and np.isfinite(sp[own[0], own[1]]) else None
    others = [(k, float(per_day[k])) for k in range(len(per_day)) if k != last_day]
    cand = [("newest_day", f"Anomaly on the newest input day ({days_in[last_day]})", float(per_day[last_day]))]
    if others:
        ek, ev = max(others, key=lambda kv: abs(kv[1]))
        cand.append(("earlier_day", f"Anomaly on the largest earlier input day ({days_in[ek]})", ev))
    cand.append(("local", f"Anomaly within ±{s['neighbourhood_deg']:g}° of this place, all input days", float(local)))
    if own_val is not None:
        cand.append(("own_block", f"Anomaly in the surrounding {s['block_deg']:g}°×{s['block_deg']:g}° block, all input days", own_val))
    cand.append(("everywhere", "Anomaly everywhere in the domain, all input days", float(everywhere)))
    top_mag = max(abs(v) for _, _, v in cand) or 1.0
    signals = []
    for rank, (sid, lab, v) in enumerate(sorted(cand, key=lambda x: -abs(x[2])), start=1):
        sens = "sensitive" if abs(v) >= 0.1 else "barely sensitive"
        signals.append({"rank": rank, "id": sid, "label": lab, "contribution_c": round(v, 2), "response_when_removed_c": round(-v, 2), "relative": round(abs(v) / top_mag, 2),
                        "direction": "no clear push" if abs(v) < FLAT else "pushes the forecast warmer" if v > 0 else "pushes the forecast colder",
                        "sentence": f"Removing this anomaly (replacing it with normal conditions) would change the day +{h7 + 1} predicted anomaly by {fr.sg(-v)} °C, so the model prediction is {sens} to it."})
    side = "positive" if start_a > 0 else "negative"
    if rd["label"] == "stable":
        plain = f"The predicted SST and anomaly change only slightly over the forecast period (SST {fr.sg(rd['sst_change_c'])} °C; anomaly {fr.sg(start_a, 1)} °C to {fr.sg(end_a, 1)} °C), indicating relatively stable conditions."
    else:
        word = "warmer" if rd["label"] == "warming" else "cooler"
        first = f"The recent SST anomaly is {fr.sg(start_a, 1)} °C ({side}) and the forecast takes it to {fr.sg(end_a, 1)} °C by day +{rd['days']} (the anomaly is {fr.EXPECTED_ING[rd['anomaly_label']]})."
        if agree:
            second = f"SST was {in_dir} by {abs(in_change):.2f} °C over the {len(sst)} input days and the forecast continues in the same direction, indicating {word} conditions over the forecast period."
        else:
            second = f"SST was {in_dir} over the input window ({fr.sg(in_change)} °C) but the forecast moves {'up' if rd['label'] == 'warming' else 'down'} ({fr.sg(rd['sst_change_c'])} °C), so it is not a simple continuation of the recent trend."
        third = f" The forecast keeps the anomaly {side}, so conditions stay {'warmer' if start_a > 0 else 'colder'} than normal." if abs(end_a) >= fr.SIGN_C and start_a * end_a > 0 else ""
        plain = f"{first} {second}{third}"
    interpretation["plain"] = plain
    interpretation["forecast_outlook"] = rd["label"]
    interpretation["anomaly_outlook"] = rd["anomaly_label"]
    last3 = slice(-3, None)
    model_in = base["model"]["input"]
    inputs = {"latest_observation": w["dates"][-1], "window": {"start": w["dates"][0], "end": w["dates"][-1], "days": len(sst)}, "latest_sst_c": round(float(last), 2), "latest_anomaly_c": round(float(anom[-1]), 2),
              "sst_trend_7d_c_per_day": round(slope, 3), "sst_change_7d_c": round(in_change, 2), "anomaly_change_7d_c": round(float(anom[-1] - anom[0]), 2),
              "sst_trend_3d_c_per_day": round(float(np.polyfit(np.arange(3), sst[last3], 1)[0]), 3), "anomaly_change_3d_c": round(float(anom[-1] - anom[-3]), 2),
              "grid": model_in.get("grid"), "cell": base["cell"], "channels": model_in["channels"], "window_days": model_in["window_days"], "horizons": base["model"]["output"]["horizons"],
              "spatial_context": "The network sees the whole grid at once: each place is processed together with its neighbourhood through 3×3 convolutions repeated at every time step."}
    evidence = [rd["text"], signals[0]["sentence"] if signals else ""]
    physical = ("Cannot be established by this model. " + model_in["not_inputs"] + " The model responds to patterns in its input; it does not identify what physically drives the ocean.")
    return {**base, "available": True, "current": current, "interpretation": interpretation, "signals": signals, "inputs": inputs, "model_evidence": [e for e in evidence if e], "physical_cause": physical, "counterfactual": counterfactual, "forecast": rows, "model_explanation": expl, "kinds": EVIDENCE_KINDS,
            "matches_published_forecast": bool(np.allclose(fc, published, atol=0.02)), "persistence_c": round(last, 2),
            "sensitivity": {**s, "title": "Model sensitivity: not causal attribution",
                            "plain": f"Each number is how many °C the observed anomaly in part of the model's input contributes to the forecast at this place, measured as the forecast minus the forecast obtained when that part of the input is replaced by normal conditions. "
                                     "Positive = the observed anomaly pushes the forecast warmer. It shows what the trained network responds to; it is not evidence about the physical cause."},
            "statement": "Model-predicted contributing patterns describe what the ConvLSTM responds to in its input. They are different from a physical or environmental causal explanation, which this model cannot provide."}
