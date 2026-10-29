"""Plain-language explanations built ONLY from structured evidence the backend already returns (risk cells, heatwave events, species lookups).

No model is called and nothing is invented: every sentence is a template filled with returned values, and `grounded_in` lists the values that were used so a
reviewer can check each claim. Facts that are not in the evidence (species presence, conservation status, ecological impact) are never asserted.
"""
from __future__ import annotations

LEVEL_BANDS = "LOW below 0.25, MODERATE below 0.5, HIGH below 0.75, CRITICAL from 0.75"
FACTOR_LABEL = {"anomaly": "SST anomaly", "persistence": "heatwave persistence", "forecast": "forecast anomaly", "overlap": "species overlap"}
BIO_TEXT = {
    "observed": "OBIS species records exist in this 2°×2° block.",
    "none_recorded": "No OBIS records were found in this block although records were gathered for this area.",
    "insufficient_coverage": "No OBIS records exist in this block. That is limited biodiversity coverage, not evidence that no animals are present, so species overlap is left out of the score.",
    "unavailable": "No biodiversity data are loaded, so species overlap is not part of the score.",
}


def _direction(a: float | None) -> str:
    if a is None:
        return "has no computed anomaly"
    if a > 0.5:
        return f"{abs(a):.1f} °C warmer than normal"
    if a < -0.5:
        return f"{abs(a):.1f} °C colder than normal"
    return f"close to normal ({a:+.1f} °C)"


def _sec(id_: str, title: str, text: str, bullets: list[str] | None = None) -> dict:
    return {"id": id_, "title": title, "text": text, "bullets": bullets or []}


def contributions(factors: list[dict]) -> list[dict]:
    """Share of the final score each available factor supplies, after the methodology's weight renormalisation."""
    used = [f for f in factors if f.get("available") and f.get("value") is not None]
    total_w = sum(f["weight"] for f in used) or 1.0
    out = [{"factor": f["factor"], "label": FACTOR_LABEL.get(f["factor"], f["factor"]), "value": f["value"], "level": f.get("level"), "weight": f["weight"],
            "score_points": round(f["weight"] * f["value"] / total_w, 3), "weight_share": round(f["weight"] / total_w, 3)} for f in used]
    return sorted(out, key=lambda c: -c["score_points"])


def explain_risk_cell(cell: dict) -> dict:
    ev = cell.get("evidence") or {}
    date = cell.get("date")
    gen = (cell.get("source") or {}).get("is_observational") is False
    where = f"{abs(cell['cell']['lat']):.1f}°{'N' if cell['cell']['lat'] >= 0 else 'S'}, {abs(cell['cell']['lon_180']):.1f}°{'W' if cell['cell']['lon_180'] < 0 else 'E'}" \
        if cell.get("cell") and "lon_180" in cell["cell"] else None
    sections: list[dict] = []
    status = cell.get("status")
    unavailable = {f["factor"]: f.get("reason") for f in cell.get("factors", []) if not f.get("available")}
    grounded = {"date": date, "dataset": cell.get("dataset"), "status": status, "score": cell.get("score"), "level": cell.get("level"),
                "evidence_completeness": cell.get("evidence_completeness"), **{k: v for k, v in ev.items() if v is not None}}

    # 1. what is happening
    if status != "assessed":
        what = ("This cell has no risk level. "
                + ("The SST anomaly, the core factor, cannot be computed here for this date, so nothing can be said about its risk." if status == "insufficient_data"
                   else "No environmental data exist for this ocean cell on this date, so nothing can be said about its risk." if status == "unavailable"
                   else "It is not an assessable ocean cell."))
        sections.append(_sec("what", "What is happening", what))
        sections.append(_sec("meaning", "What to take from this", "A missing risk level is not low risk. It means the evidence needed to assess the cell is missing."))
        return {"headline": "No risk level can be given for this cell", "sections": sections, "grounded_in": grounded, "kind": "risk_cell"}
    a = ev.get("anomaly_c")
    run = ev.get("heatwave_run_days")
    hw_txt = ("It is not currently in a marine-heatwave run." if run == 0 else f"It has been inside a marine-heatwave run for {run} days." if run else
              "Heatwave information is not available for this dataset and date.")
    sections.append(_sec("what", "What is happening", f"On {date}{' at ' + where if where else ''} the sea surface is {_direction(a)}. {hw_txt}"))

    # 2. why this level
    contrib = contributions(cell.get("factors", []))
    top = contrib[0] if contrib else None
    why = f"The combined risk score is {cell['score']:.2f}, which falls in the {'MODERATE' if cell['level'] == 'MEDIUM' else cell['level']} band ({LEVEL_BANDS})."
    if top:
        why += f" The largest contribution comes from {top['label']} ({top['score_points']:.2f} of the score)."
    if len(contrib) >= 2 and cell["level"] in ("MEDIUM", "HIGH", "CRITICAL"):
        why += f" Risk is {'MODERATE' if cell['level'] == 'MEDIUM' else cell['level']} primarily because of {contrib[0]['label']} and {contrib[1]['label']}."
    gaps = [FACTOR_LABEL.get(f["factor"], f["factor"]) for f in cell.get("factors", []) if not f.get("available")]
    if gaps:
        why += f" {', '.join(gaps)} {'is' if len(gaps) == 1 else 'are'} not available here, so {'it was' if len(gaps) == 1 else 'they were'} left out (never treated as zero) and the score uses the available indicators; biodiversity coverage affects confidence, not whether the environmental risk can be calculated."
    sections.append(_sec("why", "Why this risk level", why))

    # 3. contributing factors
    sections.append(_sec("factors", "Which factors contributed most", "Each available factor is scored 0–1; its share of the final score follows the project weights, rescaled over the factors that are available.",
                         [f"{c['label']}: {c['value']:.2f} ({'MODERATE' if c['level'] == 'MEDIUM' else c['level']}), weight {c['weight_share'] * 100:.0f}% → {c['score_points']:.2f} of the score" for c in contrib]))

    # 4. supporting evidence
    bullets = []
    if a is not None:
        bullets.append(f"SST anomaly {a:+.1f} °C versus the daily climatology")
    if run is not None:
        bullets.append(f"Heatwave run length: {run} days")
    if ev.get("forecast_mean_anomaly_c") is not None:
        bullets.append(f"Mean forecast anomaly over the next days: {ev['forecast_mean_anomaly_c']:+.1f} °C (model output)")
    if ev.get("n_species") is not None and cell.get("biodiversity_evidence") == "observed":
        bullets.append(f"{ev['n_species']} species with OBIS records in the surrounding 2°×2° block")
    for f in cell.get("factors", []):
        if f.get("available") and f.get("note"):
            bullets.append(f"Note on {FACTOR_LABEL.get(f['factor'], f['factor'])}: {f['note']}")
    sections.append(_sec("evidence", "Evidence behind the classification", "These values come straight from the backend result for this cell.", bullets))

    # 5. missing / incomplete
    miss = [f"{FACTOR_LABEL.get(k, k).capitalize()} is unavailable: {r}" for k, r in unavailable.items() if k != "overlap"]
    miss.append(BIO_TEXT.get(cell.get("biodiversity_evidence", ""), ""))
    comp = cell.get("evidence_completeness")
    txt = (f"The score uses {comp * 100:.0f}% of the methodology weight; the remaining factors are left out and the used ones are rescaled. They are not counted as zero."
           if comp is not None and comp < 1 else "All four factors were available for this cell.")
    sections.append(_sec("missing", "What evidence is missing or incomplete", txt, [m for m in miss if m]))

    # 6. takeaway
    take = "This is a monitoring-priority indicator of potential environmental exposure, not a measurement of harm to any animal or habitat."
    if gen:
        take += " The underlying SST is a modelled dataset rather than direct observations (see the data source)."
    if comp is not None and comp < 1:
        take += (" Because some factors are missing, a LOW result here only means low risk on the evidence that exists." if cell.get("level") == "LOW"
                 else " Because some factors are missing, the score reflects only the evidence that exists.")
    sections.append(_sec("meaning", "What to take from this", take))
    headline = f"{'MODERATE' if cell['level'] == 'MEDIUM' else cell['level']} risk (score {cell['score']:.2f}): " + (f"sea surface {_direction(a)}" if a is not None else "anomaly unavailable")
    return {"headline": headline, "sections": sections, "grounded_in": grounded, "contributions": contrib, "kind": "risk_cell"}


def explain_event(event: dict, info: dict, species: list[dict], biodiversity_evidence: str) -> dict:
    gen = info.get("is_observational") is False
    b0, b1 = info["baseline"]
    sens = [s for s in species if s.get("iucn_category") in ("VU", "EN", "CR")]
    sections = [
        _sec("what_is", "What is a marine heatwave", "A marine heatwave is a period when sea surface temperature stays unusually high for several consecutive days compared with the expected value "
                                                  "for that place and time of year. Here it means SST above the seasonal 90th percentile for at least "
                                                  f"{info.get('min_duration_days', 5)} days (project definition, baseline {b0[:4]}–{b1[:4]})."),
        _sec("abnormality", "How abnormal the temperature is",
             f"The anomaly averages {event['current_anomaly_c']:+.1f} °C now and peaked at {event['max_anomaly_c']:+.1f} °C. Today's SST is higher than "
             f"{event['historical_percentile']:.0f}% of baseline values for this time of year. Project category: {event['category_name']}."),
        _sec("persistence", "How long it has lasted", f"{event['duration_days']} days, since {event['start_date']} (latest data {event['last_observed_date']})."
             + (f" The model forecast keeps {event['forecast_still_above_p90_day7'] * 100:.0f}% of the area above the threshold on day 7 (model output, not an observation)."
                if event.get("forecast_still_above_p90_day7") is not None else "")),
        _sec("extent", "How large it is", f"About {event['area_km2']:,.0f} km² across {event['cells']} grid cells, centred near {abs(event['centroid']['lat']):.1f}°"
                                          f"{'N' if event['centroid']['lat'] >= 0 else 'S'}, {abs(event['centroid'].get('lon_180', event['centroid']['lon'])):.1f}°"
                                          f"{'W' if event['centroid'].get('lon_180', event['centroid']['lon']) < 0 else 'E'}."),
        _sec("cumulative", "Cumulative intensity", f"{event.get('cumulative_intensity_c_days', 0):.0f} °C·days (the sum of daily anomalies over the event, averaged over its cells; "
                                                   f"maximum cell {event.get('max_cumulative_intensity_c_days', 0):.0f} °C·days)."),
    ]
    if species:
        names = ", ".join(f"{(s.get('common_name') or s['scientific_name'])} ({s['n_records']} record{'s' if s['n_records'] != 1 else ''})" for s in species[:3])
        txt = f"Stored OBIS records of {len(species)} species fall inside the event's bounding box (last 2 years), for example {names}."
        txt += (f" {len(sens)} of them are listed VU/EN/CR by their source." if sens else " No conservation-sensitive category is recorded for them in the stored data.")
    else:
        txt = ("No stored OBIS records fall inside the event's bounding box. That is limited biodiversity coverage, not evidence that no animals are present."
               if biodiversity_evidence != "observed" else "Records overlap the event.")
    sections.append(_sec("biodiversity", "Biodiversity evidence overlapping the event", txt))
    missing = ["Species presence beyond the stored OBIS sample is unknown.", "Biological impact is not measured by this system."]
    if event.get("forecast_still_above_p90_day7") is None:
        missing.append("No forecast of how long the event will last is available for this dataset.")
    if gen:
        missing.append("The SST is a modelled dataset rather than direct observations, so the event describes that dataset.")
    sections.append(_sec("missing", "What evidence is missing", "Limits of what this event record can say:", missing))
    sections.append(_sec("why", "Why it matters ecologically",
                         "Sustained warm anomalies are a recognised stressor for marine ecosystems, so large, long or intense events are given monitoring priority. "
                         "This system does not measure biological impact; overlap with recorded species indicates potential exposure only."))
    return {"headline": f"{event['category_name']} marine heatwave: {event['duration_days']} days, {event['area_km2']:,.0f} km²", "sections": sections,
            "grounded_in": {k: event[k] for k in ("id", "dataset", "duration_days", "area_km2", "max_anomaly_c", "current_anomaly_c", "cumulative_intensity_c_days", "category_name") if k in event},
            "kind": "heatwave_event"}


def explain_forecast(f: dict) -> dict:
    """Explain a regional forecast from its own numbers: what is predicted, the horizon, the baselines, the measured performance and its uncertainty."""
    n = len(f["horizons"])
    fs, ps, cs = f["forecast_sst"], f["persistence_sst"], f["climatology_sst"]
    perf = f.get("performance")
    origin = (f.get("model") or {}).get("origin")
    sections = [
        _sec("what", "What is being predicted", f"The region-mean sea surface temperature of the {f['region']['name']} for the next {n} days after {f['issued_from']}, from the ConvLSTM model "
                                                f"({f['model']['name']}). The last observed regional mean was {f['last_observed_sst']:.1f} °C ({f['last_observed_anomaly']:+.1f} °C versus the daily climatology)."
             if f.get("last_observed_sst") is not None else "No valid cells in this region, so nothing is predicted."),
        _sec("horizon", "Forecast horizon", f"{f['target_dates'][0]} to {f['target_dates'][-1]} ({n} daily steps)."
             + (f" At day {n} the model gives {fs[-1]:.1f} °C ({f['forecast_anomaly'][-1]:+.1f} °C versus climatology)." if fs[-1] is not None else "")),
        _sec("baseline", "What it is compared with", "Two reference forecasts: persistence (tomorrow equals the last observed temperature) and climatology (the typical value for that day of the year).",
             [f"Day {n}: forecast {fs[-1]:.1f} °C, persistence {ps[-1]:.1f} °C, climatology {cs[-1]:.1f} °C"] if fs[-1] is not None and ps[-1] is not None and cs[-1] is not None else []),
    ]
    if perf:
        m = perf["models"]
        skill = [f"{x * 100:+.1f}%" for x in perf["mae_skill_vs_persistence"]]
        txt = (f"On this dataset's held-out test period ({perf['date_range'][0]} to {perf['date_range'][1]}, {perf['n_windows']} forecast windows, whole domain) the model's mean absolute error was "
               f"{m['convlstm']['mean_mae']:.2f} °C, persistence {m['persistence']['mean_mae']:.2f} °C and climatology {m['climatology']['mean_mae']:.2f} °C.")
        txt += (" The model beat persistence at every horizon." if perf["beats_persistence"] else " The model did NOT beat persistence at every horizon, so a persistence forecast is at least as reliable here.")
        sections.append(_sec("performance", "How well it has performed (measured)", txt, [f"MAE skill versus persistence by horizon: {', '.join(skill)} (positive = better)"]))
        if f.get("typical_error_c"):
            e = f["typical_error_c"]
            sections.append(_sec("uncertainty", "Uncertainty", f"Typical absolute error of this model on this dataset was {e[0]:.2f} °C at day 1 and {e[-1]:.2f} °C at day {n}. Differences smaller than that are not meaningful."))
    else:
        sections.append(_sec("performance", "How well it has performed", "No evaluation of this model on this dataset has been run, so no accuracy is claimed."))
    hc = f.get("heatwave_continuation")
    if hc:
        hc_bul = []
        if hc.get("available") and hc.get("share_still_above_day7") is not None:
            hc_bul = [f"Active events: {hc['events']} covering about {hc['area_km2']:,.0f} km²", f"Predicted to remain above the heatwave threshold on day {n}: {hc['share_still_above_day7'] * 100:.0f}% of that area"]
        sections.append(_sec("heatwave", "Marine-heatwave continuation (prediction)", hc["message"] + " This is a model prediction, not an observation.", hc_bul))
    if origin and not origin.get("retrained", True):
        sections.append(_sec("provenance", "Model provenance", f"The model weights were trained on {origin['trained_on']} and were not retrained for this dataset."))
    sections.append(_sec("meaning", "What to infer", "Treat this as a model estimate of regional-mean change, not an observation. Use the comparison with persistence and the measured error to judge how much weight it deserves."
                                                        + (" The SST it is applied to is a modelled dataset rather than direct observations." if (f.get("dataset_generated")) else "")))
    return {"headline": f"Forecast for the {f['region']['name']}: {fs[-1]:.1f} °C on {f['target_dates'][-1]}" if fs[-1] is not None else "No forecast", "sections": sections, "kind": "forecast"}


ANOMALY_CLASSES = [(3.0, "extreme"), (2.0, "strong"), (1.0, "moderate"), (0.5, "weak")]


def anomaly_class(a: float | None) -> str | None:
    """Words for the size of a departure from the daily climatology (the dashboard's SST-departure bands, |anomaly| degC)."""
    if a is None:
        return None
    for lim, name in ANOMALY_CLASSES:
        if abs(a) >= lim:
            return f"{name} {'warm' if a > 0 else 'cold'} anomaly"
    return "near normal"


def explain_anomaly(ctx: dict) -> dict:
    """Explain a cell's SST anomaly for a non-specialist, from returned values only: what it is, how large, how unusual (region, neighbours), how persistent, its relation
    to a marine heatwave, what the data can and cannot say about a cause (observed / inferred / unconfirmed), and the general ecological background. ctx: sst, normal,
    anomaly, date, region_name, region_percentile, neighbourhood_mean, neighbourhood_cells, baseline, heatwave {inside, run_days, event, available}."""
    a, sst, normal = ctx["anomaly"], ctx["sst"], ctx["normal"]
    if a is None:
        return {"headline": "No anomaly can be computed here", "sections": [_sec("what", "What is the anomaly", "The climatology needed to compute an anomaly does not exist for this cell and day.")]}
    word = "warmer than normal" if a > 0.5 else "colder than normal" if a < -0.5 else "close to normal"
    b = ctx.get("baseline")
    base_txt = f"the {b[0][:4]}–{b[1][:4]} record of this dataset" if b else "the dataset's climatological record"
    hw = ctx.get("heatwave") or {}
    secs = [_sec("what", "What is the anomaly",
                 f"The anomaly is today's sea surface temperature minus the normal temperature for this place on this day of the year, where normal is the average for this calendar day in {base_txt}. "
                 f"On {ctx['date']} the SST is {sst:.1f} °C against a normal of {normal:.1f} °C, so the anomaly is {a:+.1f} °C: {word} ({anomaly_class(a)}).")]
    bl = []
    if ctx.get("region_percentile") is not None:
        p = ctx["region_percentile"]
        bl.append(f"{'Warmer' if a >= 0 else 'Colder'} than {p if a >= 0 else 100 - p:.0f}% of the ocean cells with data in the {ctx['region_name']} today (regional comparison).")
    hist = ctx.get("history")
    if hist and hist.get("percentile") is not None:
        p = hist["percentile"]
        tail = p if a < 0 else 100 - p
        label = ("exceptionally unusual" if tail <= 1 else "strongly unusual" if tail <= 5 else "moderately unusual" if tail <= 15 else "within the usual range")
        bl.append(f"Compared with the same season (±15 days) at this cell on {hist['n']:,} earlier days, today's anomaly is {'warmer' if a >= 0 else 'colder'} than "
                  f"{p if a >= 0 else 100 - p:.0f}% of them: {label} (historical distribution; statistical inference).")
    n = ctx.get("neighbourhood_mean")
    if n is not None:
        bl.append(f"The {ctx['neighbourhood_cells']} surrounding cells average {n:+.1f} °C, so this cell is {'about as anomalous as' if abs(n - a) < 0.5 else 'more anomalous than' if abs(a) > abs(n) else 'less anomalous than'} its neighbours (neighbouring-cell comparison).")
    secs.append(_sec("unusual", "How unusual is it", f"Against the climatology this is a {anomaly_class(a)}.", bl))
    if hw.get("inside") and hw.get("event"):
        e = hw["event"]
        secs.append(_sec("persistence", "Persistence and marine heatwave",
                         f"This cell has been above the seasonal 90th-percentile threshold for {hw['run_days']} days and belongs to a {e['category_name']} marine heatwave that started {e['start_date']}, "
                         f"covers {e['area_km2']:,.0f} km² and has reached {e['max_anomaly_c']:+.1f} °C. The anomaly is therefore persistent, not a one-day fluctuation."))
    elif hw.get("available") is False:
        secs.append(_sec("persistence", "Persistence and marine heatwave", "Marine-heatwave persistence is only computed for the dataset's latest date, so it cannot be assessed for this date."))
    else:
        secs.append(_sec("persistence", "Persistence and marine heatwave", "SST at this cell has not stayed above the seasonal 90th percentile for 5 or more days, so it is not in a marine heatwave."))
    coherent = n is not None and abs(a) >= 0.5 and abs(n) >= 0.5 and (n > 0) == (a > 0)
    observed = [f"SST {sst:.1f} °C, normal {normal:.1f} °C, anomaly {a:+.1f} °C."]
    clim = ctx.get("climate")
    if clim:
        if clim.get("oni"):
            o = clim["oni"]
            observed.append(f"Climate context (NOAA Climate Prediction Center): the Oceanic Niño Index for {o['season']} is {o['value']:+.2f} °C, which is {'at or above +0.5 °C, the threshold NOAA uses for El Niño conditions' if o['state'].startswith('El') else 'at or below −0.5 °C, the threshold NOAA uses for La Niña conditions' if o['state'].startswith('La') else 'between −0.5 and +0.5 °C: neutral'}.")
        if clim.get("pdo"):
            q = clim["pdo"]
            observed.append(f"Climate context (NOAA NCEI): the Pacific Decadal Oscillation index for {q['month']} is {q['value']:+.2f}, the {q['phase']} phase.")
    inferred = []
    if coherent:
        inferred.append("The neighbouring cells share the sign of the anomaly, which points to a spatially coherent water mass or regional pattern rather than a local measurement effect.")
    if hw.get("inside"):
        inferred.append("The multi-day persistence is consistent with marine-heatwave conditions.")
    if not inferred:
        inferred.append("No pattern in the available data supports an interpretation beyond the departure itself.")
    possible = []
    if hw.get("inside"):
        possible.append("Persistent regional warming of the surface layer, of the kind that sustains marine heatwaves, could account for a multi-day departure of this size.")
    elif abs(a) >= 0.5:
        possible.append("A seasonal shift that is earlier or later than the climatological average, or warm or cold water moving in from neighbouring cells, could account for a departure of this size.")
    else:
        possible.append("The departure is small enough to be ordinary day-to-day variability around the climatological average.")
    if clim and clim.get("oni") and clim["oni"]["state"] != "neutral" and abs(ctx.get("lat") or 99) <= 20 and ((ctx.get("lon_180") or 0) >= 160 or (ctx.get("lon_180") or 0) <= -80) and abs(a) >= 0.5:
        o = clim["oni"]
        possible.append(f"The tropical central and eastern Pacific usually runs {'warmer' if o['state'].startswith('El') else 'cooler'} than normal during {o['state'].split(' conditions')[0]} (Oceanic Niño Index {o['value']:+.2f} °C), so this anomaly may be partly associated with it. "
                        "That association is general knowledge; this analysis has not tested it for this place.")
    if clim and clim.get("pdo") and (ctx.get("lat") or 0) >= 20 and abs(a) >= 0.5:
        q = clim["pdo"]
        possible.append(f"The Pacific Decadal Oscillation is in its {q['phase']} phase ({q['value']:+.2f}); PDO phase is associated with regional SST patterns in the North Pacific, but this analysis has not tested whether it explains this anomaly.")
    unconfirmed = ["Physical causes (large-scale climate modes, ocean currents, upwelling, wind and heat exchange with the atmosphere) are not established by this dataset"
                   + (": the climate indices above describe basin-wide conditions and do not show that they caused the anomaly at this place." if clim else ", and no climate-index data are loaded, so no link to El Niño, La Niña or the PDO is claimed.")]
    secs.append(_sec("why", "What could be contributing", "Separating what was measured, what is statistically inferred, what is only a possible explanation, and what the data cannot establish:",
                     [f"Observed: {t}" for t in observed] + [f"Inferred (from the data): {t}" for t in inferred] + [f"Possible explanation (not tested): {t}" for t in possible]
                     + [f"Not established by available data: {t}" for t in unconfirmed] + ["The available observations cannot establish a physical cause."]))
    sig = ("Persistent warm surface water can raise thermal stress for temperature-sensitive marine life and shift where species are found; this is general background, and this system does not measure biological impact."
           if a > 0.5 else "Persistent cold anomalies can also stress species adapted to warmer water; this is general background, and this system does not measure biological impact." if a < -0.5
           else "A near-normal temperature carries no unusual thermal signal for marine life at this place and time.")
    secs.append(_sec("consequences", "Potential environmental significance", sig))
    return {"headline": f"{anomaly_class(a).capitalize()}: {a:+.1f} °C versus normal", "sections": secs, "kind": "anomaly",
            "grounded_in": {k: ctx.get(k) for k in ("date", "sst", "normal", "anomaly", "region_percentile", "neighbourhood_mean")}}


def explain_species(x: dict) -> dict:
    """Explain one species' exposure from the aggregated numbers of its stored records (location_report.species_exposure). Records are observations, never a range."""
    name = x.get("common_name") or x["scientific_name"]
    cs = x["conservation_status"]
    secs = [_sec("where", "Where it has been recorded",
                 f"{x['n_records']} stored OBIS record{'s' if x['n_records'] != 1 else ''} in {x['n_cells']} grid cell{'s' if x['n_cells'] != 1 else ''}, between {x['latitude_range'][0]:.1f}° and {x['latitude_range'][1]:.1f}° latitude"
                 + (f", mostly in the {x['top_region']}" if x.get("top_region") else "") + f"; latest record {x['latest_record']}. These are observation records (record density), not the species' range, and the absence of a record is not absence of the species.")]
    secs.append(_sec("conditions", "Environmental conditions at those records",
                     f"On {x['date']} the sea surface at the recorded locations averages {x['mean_anomaly_c']:+.1f} °C against normal (maximum {x['max_anomaly_c']:+.1f} °C); "
                     f"{x['share_anomaly_1c'] * 100:.0f}% of the records lie in cells at least 1 °C from normal."))
    if x["heatwave_available"]:
        secs.append(_sec("heatwave", "Overlap with marine heatwaves",
                         f"{x['share_in_heatwave'] * 100:.0f}% of the records lie inside a current marine heatwave." if x["share_in_heatwave"] > 0 else "None of the records lies inside a current marine heatwave."))
    else:
        secs.append(_sec("heatwave", "Overlap with marine heatwaves", "Marine-heatwave status is only computed for the dataset's latest date, so overlap cannot be assessed for this date."))
    if x["share_high_risk"] is not None:
        secs.append(_sec("risk", "Overlap with ecological risk", f"{x['share_high_risk'] * 100:.0f}% of the records lie in cells rated HIGH or CRITICAL ecological risk (highest level: {x['highest_risk_level'] or 'not assessed'})."))
    if x.get("mean_forecast_anomaly_c") is not None:
        secs.append(_sec("forecast", "Forecast exposure (model prediction)", f"The model predicts a mean anomaly of {x['mean_forecast_anomaly_c']:+.1f} °C over the next days at the recorded locations. This is a prediction, not an observation."))
    if x.get("alert_severity"):
        secs.append(_sec("alert", "Related alert", f"A {x['alert_severity']} species-exposure alert exists for this species on this date."))
    cons = (f"{name} is listed {cs} ({x['conservation_source']})." if x.get("conservation_source") else f"The conservation status of {name} is not confirmed in the stored data.")
    cons += (" A threatened category makes exposure to persistent warm conditions a conservation-relevant concern, although this system does not measure harm to the species." if x["conservation_sensitive"]
             else " Exposure is reported as potential exposure only; this system does not measure harm to the species.")
    secs.append(_sec("conservation", "Why it matters for conservation", cons))
    return {"headline": f"{name}: {x['share_in_heatwave'] * 100:.0f}% of records inside a marine heatwave" if x["heatwave_available"] else f"{name}: exposure at its recorded locations", "sections": secs, "kind": "species"}


# ---- potential environmental implications ----------------------------------------------------------------------------------------------------
EVIDENCE_KINDS = {
    "observed": "Observed measurement",
    "model_prediction": "Model prediction",
    "statistical": "Statistical association",
    "model_explanation": "Model explanation (sensitivity of the trained model)",
    "possible_explanation": "Possible explanation (plausible, not tested by this model)",
    "physical_cause": "Not established (physical cause cannot be inferred from this model)",
    "ecological_implication": "Possible ecological implication (general knowledge, not measured here)",
}


def implications(ctx: dict) -> dict:
    """What the observed and forecast conditions at a place MAY mean for marine ecosystems, in careful language. Each statement says what kind of evidence it is. Nothing here
    says that harm has happened: this system has no observations of bleaching, mortality or changes in species distribution."""
    a = ctx.get("anomaly")
    if a is None:
        return {"available": False, "items": [], "message": "No SST anomaly exists for this place and date, so no implications are drawn.", "kinds": EVIDENCE_KINDS}
    hw, fc, sp, risk = ctx.get("heatwave") or {}, ctx.get("forecast") or {}, ctx.get("species") or {}, ctx.get("risk") or {}
    items: list[dict] = []

    def add(kind, text):
        items.append({"kind": kind, "label": EVIDENCE_KINDS[kind], "text": text})

    run = hw.get("run_days") if hw.get("inside") else None
    if a >= 1.0:
        add("observed", f"Sea surface temperature is {a:+.1f} °C above the normal for this day of the year.")
        add("ecological_implication", "Water this much warmer than normal may increase thermal stress for temperature-sensitive species and may change where some species are found.")
    elif a <= -1.0:
        add("observed", f"Sea surface temperature is {a:+.1f} °C below the normal for this day of the year.")
        add("ecological_implication", "Water this much colder than normal may increase stress for species adapted to warmer water and may change where some species are found.")
    else:
        add("observed", f"Sea surface temperature is {a:+.1f} °C from normal, within the usual range of variation.")
        add("ecological_implication", "A departure this small carries no unusual thermal signal for marine life at this place and time.")
    if run:
        add("observed", f"This cell has been in a marine-heatwave state for {run} days.")
        add("ecological_implication", "Warm conditions that last for weeks may reduce habitat suitability and alter feeding conditions for some species; longer and stronger events are given higher monitoring priority.")
    if abs(a) >= 1.0:
        hot = a > 0
        add("ecological_implication", f"Fisheries: a surface temperature {abs(a):.1f} °C {'above' if hot else 'below'} normal may shift where temperature-sensitive fish and invertebrates are found, which can change their availability to fisheries. "
                                      "This system has no catch or stock data.")
        add("ecological_implication", ("Plankton: persistent warm surface water can strengthen stratification and may reduce nutrient supply to the surface, which can affect plankton productivity. " if hot else
                                       "Plankton: colder-than-normal surface water can change stratification and nutrient supply and may shift plankton community composition. ") + "Chlorophyll and nutrients are not measured here.")
        add("ecological_implication", f"Spawning and recruitment: a departure of {a:+.1f} °C during a spawning season can affect the timing and success of spawning and the survival of larvae for some species. The spawning seasons of species here are not known to this system.")
        add("ecological_implication", f"Habitat suitability: for species with narrow thermal ranges, water {abs(a):.1f} °C {'warmer' if hot else 'colder'} than normal may reduce habitat suitability and shift species distributions.")
    if run and run >= 14:
        add("ecological_implication", f"Prolonged exposure: {run} consecutive days in heatwave conditions can increase ecological pressure on heat-sensitive species more than a short spike of the same size.")
    lat = ctx.get("lat")
    if lat is not None and a >= 1.0 and run:
        if abs(lat) <= 30:
            add("ecological_implication", "In the tropics and subtropics, reef-building corals, where they are present, are sensitive to sustained warm anomalies. Whether corals are present here, and whether bleaching "
                                          "occurs, is not known to this system (bleaching alerts come from NOAA Coral Reef Watch).")
        else:
            add("ecological_implication", "At mid and high latitudes, cool-water habitats such as kelp forests, where present, can be stressed by prolonged warm anomalies. Whether they are present here is not known to this system.")
    if fc.get("available") and fc.get("forecast_anomaly"):
        last = fc["forecast_anomaly"][-1]
        from app.services import forecast_reading as _fr
        traj = _fr.trajectory(a, last)
        keeps = traj in ("persistent", "strengthening") and abs(a) >= 0.5
        add("model_prediction", f"The ConvLSTM forecast anomaly on day {len(fc['forecast_anomaly'])} is {last:+.1f} °C, so the departure from normal is expected to {_fr.EXPECTED[traj]}. "
                                "This is a model estimate with the typical error shown in the forecast section.")
        if keeps and abs(a) >= 1.0:
            add("ecological_implication", "If the forecast verifies, the thermal stress described above would continue over the forecast period.")
    elif fc and not fc.get("available"):
        add("model_prediction", "No forecast applies to this date, so nothing is said about how conditions may continue.")
    items_sp = sp.get("items") or []
    if items_sp:
        sens = [s for s in items_sp if s.get("conservation_sensitive")]
        add("observed", f"OBIS records of {len(items_sp)} species lie within about {sp.get('radius_deg', 3):g}° of this location" + (f", {len(sens)} of them with a vulnerable, endangered or critically endangered category." if sens else "."))
        add("ecological_implication", "These species may be exposed to the conditions above. Records show where animals were observed, not their range, so this is potential exposure only.")
    else:
        add("observed", "Biodiversity coverage is limited here (no stored observations nearby), so nothing is said about which species may be exposed; additional observations would improve confidence.")
    rd = fc.get("reading") if fc.get("available") else None
    if rd and rd["label"] == "cooling" and abs(rd["sst_change_c"]) >= 0.5:
        add("model_prediction", f"The model predicts SST falling by {abs(rd['sst_change_c']):.2f} °C over {rd['days']} days (anomaly {rd['anomaly_now_c']:+.1f} °C now, {rd['anomaly_end_c']:+.1f} °C at day +{rd['days']}).")
        add("ecological_implication", f"Cooling of this size may change habitat suitability for species with narrow thermal ranges and could shift where some species are found. Cooler surface water can also be associated with changes "
                                      "in mixing and productivity, and may alter the behaviour of temperature-sensitive animals such as feeding and movement. None of this is measured here.")
    ob = ctx.get("obis") or {}
    if ob.get("available") and ob.get("exposure_text"):
        c = ob["counts"]
        add("observed", f"{ob['label']} {c['threatened_species']} of the {c['distinct_species']:,} species carry a threatened (CR, EN or VU) IUCN Red List category in OBIS.")
        add("ecological_implication", ob["exposure_text"])
    elif ob.get("available"):
        add("observed", ob["label"])
    cx = ctx.get("context") or {}
    if (cx.get("chlorophyll") or {}).get("available"):
        add("observed", cx["chlorophyll"]["text"])
    if (cx.get("currents") or {}).get("available"):
        add("observed", cx["currents"]["text"])
    if risk.get("level"):
        add("statistical", f"The project risk indicator is {'MODERATE' if risk['level'] == 'MEDIUM' else risk['level']} ({risk.get('score'):.2f}). It combines the factors above by fixed weights; it ranks monitoring priority and is not a measurement of harm.")
    return {"available": True, "items": items, "kinds": EVIDENCE_KINDS,
            "caveat": "These are possible implications drawn from general ecological knowledge. This system has no observations of damage, bleaching, mortality or changes in species distribution, and it does not claim any."}
