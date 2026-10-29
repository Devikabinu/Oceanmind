"""From measured physical context to an honest explanation: which indicators are consistent with the observed SST anomaly, which are not, which cannot be assessed, and how all of it
relates to the ConvLSTM forecast.

The rules are fixed and visible in the output (`method`), and every verdict is one of
  consistent        the indicator moves the way the mechanism predicts for this anomaly;
  not consistent    it moves the opposite way (evidence AGAINST the mechanism);
  inconclusive      the indicator is within its normal range or too small to say;
  not assessable    the needed data or physics are not available at this place.
No verdict is ever "cause established": consistency of an indicator with an anomaly is evidence for a plausible mechanism, not attribution. The ConvLSTM sensitivity analysis is never
used as evidence about the ocean. Driver values are the latest OBSERVATIONS; no forecast of them exists here."""
from __future__ import annotations

import math
from datetime import date, datetime

import numpy as np

from app.services import forecast_reading as fr
from app.services import physical_drivers as pdv

Z_MODERATE = 1.0               # a wind or stress anomaly beyond this many standard deviations of the 2016-2025 same-window values counts as a departure
Z_STRONG = 2.0
SLA_M = 0.03                   # a 7-day mean sea level departure (from the same days of 2016-2025) smaller than 3 cm is treated as within altimetry noise: a judgement threshold, not a validated error bound
ADV_C_PER_DAY = 0.02           # an advective temperature tendency smaller than this is too small to compare with the observed trend
ANOMALY_C = 0.5                # an SST anomaly smaller than this has nothing to explain
EQUATOR_DEG = 3.0

METHOD = [
    "Wind: the 7-day mean wind speed and zonal/meridional stress at the place are compared with the same 7 calendar days of 2016-2025 (CCMP); a departure is |z| ≥ 1 (z = departure / standard deviation of the yearly values).",
    "Mechanism for warming: weaker winds reduce turbulent mixing and latent heat loss; for cooling the reverse. Verdict 'consistent' needs the wind departure to have that sign.",
    "Advection: geostrophic current (altimetry) times the OISST temperature gradient gives −u·∇T in °C/day. It is 'consistent' with an anomaly when it warms (cools) the water at a warm (cold) anomaly; its sign relative to the observed 7-day SST trend is reported separately. The total current is used, so the normal (climatological) advection that is already part of the normal SST is included: only an anomalous current or gradient could explain an anomaly, and that split is not computed. Wind-driven currents are not included.",
    "Upwelling: on the equator (|latitude| < 3°) and only where the normal stress is easterly, a weaker-than-normal easterly stress means less upwelling of cool water; near a coast, the Ekman transport normal to the coast is compared with its normal value. Elsewhere the stress curl would be needed and is not computed.",
    "Sea level: the altimetry product is relative to a long-term mean sea surface and keeps the seasonal cycle, so the 7-calendar-day mean is compared with the same days of 2016-2025; a departure of at least 3 cm and |z| ≥ 1 above (below) normal is consistent with a deeper (shallower) warm layer. Eddies and non-thermal effects also change sea level.",
    "ENSO: Niño 3.4 and ONI describe a basin-scale state; only in the central and eastern tropical Pacific is a matching sign called consistent, elsewhere it is context.",
    "Heat flux: NASA POWER radiation, air temperature and humidity, CCMP wind and the OISST over the same seven days give a bulk ESTIMATE (not a measurement) of the surface heat-flux anomaly (that week's atmosphere over that week's SST minus the same week of 2016-2025 over the normal SST). It has not been validated against measured fluxes in this project; 10 W/m² is only the judgement threshold below which the sign is not interpreted. A surface that loses heat over a warm anomaly is damping it, not building it.",
]


def _d(s: str | None) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def _lag(sst_date: date, other: str | None) -> int | None:
    o = _d(other)
    return None if o is None else (sst_date - o).days


def enso_region(lat: float, lon: float) -> bool:
    """True in the central and eastern tropical Pacific, where ENSO changes SST directly (15°S-15°N, 160°E-80°W)."""
    return abs(lat) <= 15 and 160 <= pdv.lon360(lon) <= 280


def _mech(mid, name, kind, verdict, favours, support, against, data, caveat, quality):
    return {"id": mid, "name": name, "kind": kind, "verdict": verdict, "favours": favours, "evidence_for": support, "evidence_against": against, "data": data, "caveat": caveat, "evidence_quality": quality}


def _side(a: float) -> str:
    return "warm" if a > 0 else "cold"


# ------------------------------------------------------------------------------------------------------------------------ mechanisms
def wind_mechanism(w: dict | None, a: float) -> dict:
    name = "Wind-driven mixing and evaporative heat exchange"
    if not w or not w.get("available"):
        return _mech("wind", name, "measurement", "not assessable", None, [], [], [], (w or {}).get("message", "Wind data were not retrieved."), "none")
    rec, an, base = w["recent"], w.get("anomaly"), w.get("baseline")
    data = [{"label": "Mean wind speed", "value": round(rec["speed"], 2), "unit": "m/s", "period": f"{w['window']['start']} to {w['window']['end']}", "kind": "measurement (analysis)"},
            {"label": "Wind direction (from)", "value": rec["direction_from_deg"], "unit": "°", "period": f"{w['window']['start']} to {w['window']['end']}", "kind": "measurement (analysis)"}]
    if not an or an.get("speed_z") is None:
        return _mech("wind", name, "measurement", "not assessable", None, [], [], data, w.get("baseline_message", "No baseline for this place and season."), "low")
    z = an["speed_z"]
    data += [{"label": "Departure of wind speed from the 2016-2025 same-week mean", "value": an["speed"], "unit": "m/s", "period": f"z = {z:+.1f}", "kind": "derived"}]
    line = (f"The 7-day mean wind speed ({w['window']['start']} to {w['window']['end']}) was {rec['speed']:.1f} m/s, {abs(an['speed']):.1f} m/s {'below' if an['speed'] < 0 else 'above'} the "
            f"{base['years'][0]}-{base['years'][-1]} average for the same dates ({base['speed']['mean']:.1f} ± {base['speed']['sd']:.1f} m/s; z = {z:+.1f}).")
    if abs(a) < ANOMALY_C:
        return _mech("wind", name, "measurement", "inconclusive", None, [], [], data, "The SST anomaly is small, so there is no anomaly for the wind to explain.", "moderate")
    want_weaker = a > 0
    favours = "warming" if z <= -Z_MODERATE else "cooling" if z >= Z_MODERATE else None
    if abs(z) < Z_MODERATE:
        return _mech("wind", name, "measurement", "inconclusive", None, [], [line + " This is within the normal range, so the winds do not point to a wind-driven change."], data, "Winds near normal neither support nor rule out the mechanism.", "moderate")
    supports = (want_weaker and z <= -Z_MODERATE) or (not want_weaker and z >= Z_MODERATE)
    how = ("Weaker winds reduce turbulent mixing of the surface layer and evaporative (latent) heat loss, which may favour a warm anomaly." if want_weaker else
           "Stronger winds increase mixing with cooler water below and evaporative heat loss, which may favour a cold anomaly.")
    if supports:
        return _mech("wind", name, "measurement", "consistent", favours, [line, how], [], data,
                     "A 7-day mean of an analysed wind field at 0.25° says nothing about the timing of the SST response; mixing also depends on stratification, which is not measured here.", "moderate" if abs(z) >= Z_STRONG else "low")
    return _mech("wind", name, "measurement", "not consistent", favours, [], [line, f"{'Stronger' if z > 0 else 'Weaker'} winds would tend to {'cool' if z > 0 else 'warm'} the surface, the opposite of the {_side(a)} anomaly."], data,
                 "Another process must dominate if the anomaly is being maintained; the data here do not say which.", "moderate" if abs(z) >= Z_STRONG else "low")


def upwelling_mechanism(w: dict | None, a: float, lat: float, coast: dict | None) -> dict:
    name = "Wind-driven upwelling and Ekman transport"
    if not w or not w.get("available"):
        return _mech("upwelling", name, "derived", "not assessable", None, [], [], [], (w or {}).get("message", "Wind data were not retrieved."), "none")
    rec, an, base = w["recent"], w.get("anomaly"), w.get("baseline")
    ek = pdv.ekman_transport(lat, rec["taux"], rec["tauy"])
    data = [{"label": "Zonal wind stress (+ = toward the east)", "value": round(rec["taux"], 4), "unit": "N/m²", "period": f"{w['window']['start']} to {w['window']['end']}", "kind": "derived (bulk formula from the wind)"}]
    if an and base:
        data.append({"label": "Departure of zonal stress from the 2016-2025 same-week mean", "value": an["taux"], "unit": "N/m²", "period": f"z = {an['taux_z']:+.1f}" if an.get("taux_z") is not None else "", "kind": "derived"})
    if abs(a) < ANOMALY_C:
        return _mech("upwelling", name, "derived", "inconclusive", None, [], [], data, "The SST anomaly is small, so there is no anomaly for upwelling to explain.", "low")
    if abs(lat) < EQUATOR_DEG:
        if not (an and base) or an.get("taux_z") is None:
            return _mech("upwelling", name, "derived", "not assessable", None, [], [], data, "No baseline for the equatorial stress at this season.", "low")
        z, normal = an["taux_z"], base["taux"]["mean"]
        if normal > -0.01:                                                                       # the rule below is about a normally easterly (negative) stress
            return _mech("upwelling", name, "derived", "not assessable", None, [], [], data,
                         f"The normal zonal stress at this longitude and season is {normal:+.3f} N/m² (not clearly easterly), so a change in stress cannot be read as a change in equatorial upwelling.", "none")
        line = (f"Zonal stress over the last 7 days was {rec['taux']:+.3f} N/m² against a {base['years'][0]}-{base['years'][-1]} same-week mean of {normal:+.3f} N/m² (z = {z:+.1f}); on the equator "
                "easterly (negative) stress drives upwelling of cooler water, so a stress that is less negative than normal means weaker upwelling.")
        if abs(z) < Z_MODERATE:
            return _mech("upwelling", name, "derived", "inconclusive", None, [], [line + " The departure is within the normal range."], data, "Equatorial upwelling also depends on the thermocline depth, which is not measured here.", "low")
        weaker = z > 0                                                                           # taux less negative (normal is easterly) = weaker upwelling
        favours = "warming" if weaker else "cooling"
        ok = (a > 0 and weaker) or (a < 0 and not weaker)
        return _mech("upwelling", name, "derived", "consistent" if ok else "not consistent", favours, [line] if ok else [], [] if ok else [line + f" That would tend to {favours[:-3]} the surface, opposite to the {_side(a)} anomaly."], data,
                     "The stress is derived from the wind with a bulk formula; thermocline depth and the equatorial undercurrent are not measured here.", "moderate" if abs(z) >= Z_STRONG else "low")
    if ek is None:
        return _mech("upwelling", name, "derived", "not assessable", None, [], [], data, "Ekman transport is not defined this close to the equator.", "none")
    mx, my = ek
    data.append({"label": "Ekman transport", "value": round(math.hypot(mx, my), 2), "unit": "m²/s", "period": f"toward {round((math.degrees(math.atan2(mx, my)) + 360) % 360)}° (clockwise from north)", "kind": "derived"})
    if coast and coast.get("near_coast") and coast.get("offshore") and base:
        off = lambda x, y: x * coast["offshore"][0] + y * coast["offshore"][1]                    # noqa: E731
        now = off(mx, my)
        bk = pdv.ekman_transport(lat, base["taux"]["mean"], base["tauy"]["mean"])
        if bk is not None:
            normal = off(*bk)
            delta = now - normal
            data.append({"label": "Ekman transport away from the coast (+ = offshore, upwelling-favourable)", "value": round(now, 2), "unit": "m²/s", "period": f"normal {normal:+.2f} m²/s", "kind": "derived"})
            line = (f"Ekman transport directed away from the nearby coast was {now:+.2f} m²/s against a normal {normal:+.2f} m²/s ({coast['land_fraction'] * 100:.0f}% of the surrounding cells are land); "
                    "offshore transport brings cooler water up to replace the surface water, so a reduction in it favours warming.")
            if abs(delta) < max(0.25 * abs(normal), 0.3):
                return _mech("upwelling", name, "derived", "inconclusive", None, [], [line + " The departure is small."], data, "The coastline direction is estimated from the 0.25° land mask and is approximate.", "low")
            favours = "warming" if delta < 0 else "cooling"
            ok = (a > 0 and delta < 0) or (a < 0 and delta > 0)
            return _mech("upwelling", name, "derived", "consistent" if ok else "not consistent", favours, [line] if ok else [], [] if ok else [line + f" That favours {favours}, opposite to the {_side(a)} anomaly."], data,
                         "The coastline direction is estimated from the 0.25° land mask and is approximate; coastal upwelling also depends on shelf shape and stratification.", "low")
    return _mech("upwelling", name, "derived", "not assessable", None, [], [], data,
                 "Away from the equator and any coast, open-ocean upwelling depends on the curl of the wind stress, which is not computed here; the Ekman transport above is shown for information only.", "none")


def advection_mechanism(cur: dict | None, adv: dict | None, trend: float | None, lat: float, a: float) -> dict:
    name = "Horizontal heat transport by ocean currents"
    if not cur or not cur.get("available") or not adv or trend is None:
        return _mech("advection", name, "derived", "not assessable", None, [], [], [], "Current or SST-gradient data were not available at this place.", "none")
    u = cur["latest"]["u"]
    v = cur["latest"]["v"]
    tend = -(u * adv["dTdx_c_per_m"] + v * adv["dTdy_c_per_m"]) * 86400.0
    data = [{"label": "Geostrophic surface current", "value": round(math.hypot(u, v), 2), "unit": "m/s", "period": cur["latest"]["date"], "kind": "measurement (altimetry)"},
            {"label": "SST gradient", "value": round(math.hypot(adv["dTdx_c_per_m"], adv["dTdy_c_per_m"]) * 1e5, 2), "unit": "°C per 100 km", "period": adv["date"], "kind": "derived (OISST)"},
            {"label": "Advective SST tendency, −u·∇T", "value": round(tend, 3), "unit": "°C/day", "period": cur["latest"]["date"], "kind": "derived"},
            {"label": "Observed SST trend", "value": round(trend, 3), "unit": "°C/day", "period": "last 7 days", "kind": "measurement"}]
    if abs(lat) < EQUATOR_DEG:
        data = [x for x in data if not x["label"].startswith("Advective")]                    # a tendency that is not interpreted here is not displayed either
        data[0] = {**data[0], "label": "Geostrophic surface current (not reliable within 3° of the equator)"}
        return _mech("advection", name, "derived", "not assessable", None, [], [], data, "The geostrophic approximation fails within about 3° of the equator, so the advective tendency is not interpreted here.", "none")
    line = (f"The geostrophic current ({math.hypot(u, v):.2f} m/s) acting on the observed SST gradient gives an advective tendency of {tend:+.3f} °C/day, against an observed 7-day SST trend of {trend:+.3f} °C/day.")
    if abs(tend) < ADV_C_PER_DAY:
        return _mech("advection", name, "derived", "inconclusive", None, [], [line + " The advective tendency is too small to account for the observed trend."], data, "Only the geostrophic part of the current is included; wind-driven currents are not.", "low")
    favours = "warming" if tend > 0 else "cooling"
    pushes_anomaly = (tend > 0) == (a > 0)                                           # it moves the temperature in the direction of the anomaly
    same_as_trend = (tend > 0) == (trend > 0)
    frac = abs(tend / trend) if abs(trend) > 1e-6 else None
    rel = (f" The observed 7-day SST trend has the {'same' if same_as_trend else 'opposite'} sign" + (f" (the advective tendency is about {frac * 100:.0f}% of it in magnitude)." if frac is not None else "."))
    norm = ("The total geostrophic current is used, so the normal advection that is already part of the normal SST is included; an anomalous current or gradient would be needed to explain an anomaly, and that split is not computed. "
            "Only the geostrophic part of the current is included; wind-driven currents and vertical processes are not.")
    if abs(a) < ANOMALY_C:
        return _mech("advection", name, "derived", "inconclusive", None, [], [line + rel], data, "The SST anomaly is small, so there is no anomaly for advection to explain. " + norm, "low")
    if pushes_anomaly:
        return _mech("advection", name, "derived", "consistent", favours, [line + f" It would {favours[:-3]} the water, the direction of the {_side(a)} anomaly." + rel], [], data, norm, "low")
    return _mech("advection", name, "derived", "not consistent", favours, [], [line + f" It would {favours[:-3]} the water, opposite to the {_side(a)} anomaly." + rel], data, norm, "low")


def sea_level_mechanism(s: dict | None, a: float) -> dict:
    name = "Upper-ocean heat content (sea level anomaly)"
    if not s or not s.get("available"):
        return _mech("sea_level", name, "measurement", "not assessable", None, [], [], [], (s or {}).get("message", "Sea level data were not retrieved."), "none")
    m = s["recent_mean_m"]
    win = s.get("window") or {"start": "", "end": s["latest"]["date"]}
    period = f"{win['start']} to {win['end']}" if win.get("start") else f"to {s['latest']['date']}"
    data = [{"label": "Sea level anomaly (relative to the long-term mean surface), 7-day mean", "value": round(m * 100, 1), "unit": "cm", "period": period, "kind": "measurement (altimetry)"}]
    bl = s.get("baseline")
    if bl:
        data.append({"label": f"Departure from the {bl['years'][0]}-{bl['years'][-1]} mean of the same days", "value": round(s["departure_m"] * 100, 1), "unit": "cm", "period": f"z = {s['departure_z']:+.1f}" if s.get("departure_z") is not None else "", "kind": "derived"})
    if abs(a) < ANOMALY_C:
        return _mech("sea_level", name, "measurement", "inconclusive", None, [], [], data, "The SST anomaly is small, so there is no anomaly to compare with.", "low")
    seasonal = ("The product is relative to a long-term mean sea surface and keeps the seasonal cycle, so the raw value alone cannot be read as an anomaly of this year; sea level also reflects salinity, eddies and non-thermal changes.")
    if not bl or s.get("departure_z") is None:
        return _mech("sea_level", name, "measurement", "inconclusive", None, [], [f"The 7-day mean sea level is {m * 100:+.1f} cm relative to the long-term mean surface, but the same days of other years could not be retrieved, so its departure from the normal for this season is not known."],
                     data, seasonal + " " + s.get("baseline_message", ""), "low")
    d, z = s["departure_m"], s["departure_z"]
    line = (f"The 7-day mean sea level was {m * 100:+.1f} cm, {abs(d) * 100:.1f} cm {'above' if d > 0 else 'below'} the {bl['years'][0]}-{bl['years'][-1]} mean of the same days ({bl['mean_m'] * 100:+.1f} ± {bl['sd_m'] * 100:.1f} cm; z = {z:+.1f}). "
            "Higher sea level is associated with a deeper layer of warm water (thermal expansion), lower with a shallower one.")
    if abs(d) < SLA_M or abs(z) < Z_MODERATE:
        return _mech("sea_level", name, "measurement", "inconclusive", None, [], [line + " This is within the normal range for the season, so it neither supports nor weakens the anomaly."], data, seasonal, "low")
    ok = (a > 0 and d > 0) or (a < 0 and d < 0)
    favours = "warming" if d > 0 else "cooling"
    return _mech("sea_level", name, "measurement", "consistent" if ok else "not consistent", favours, [line] if ok else [], [] if ok else [line + f" That points to a {'warm' if d > 0 else 'cool'} layer, opposite to the {_side(a)} SST anomaly."], data,
                 "Sea level is an indirect proxy for heat content. " + seasonal, "low")


def enso_mechanism(e: dict | None, a: float, lat: float, lon: float) -> dict:
    name = "ENSO state (climate-scale context)"
    if not e or not e.get("available"):
        return _mech("enso", name, "context", "not assessable", None, [], [], [], (e or {}).get("message", "ENSO indices were not retrieved."), "none")
    n34 = e["nino34_anomaly"]
    oni = e.get("oni")
    state = "El Niño" if n34 >= 0.5 else "La Niña" if n34 <= -0.5 else "neutral"       # the monthly Niño 3.4 anomaly against the ±0.5 °C ENSO thresholds; NOAA's official state also needs persistence and the atmosphere
    data = [{"label": f"Niño 3.4 SST anomaly, {e['latest_month']}", "value": n34, "unit": "°C", "period": e["latest_month"], "kind": "contextual climate index"}]
    if oni:
        data.append({"label": f"Oceanic Niño Index, {oni['season']}", "value": oni["value"], "unit": "°C", "period": oni["season"], "kind": "contextual climate index"})
    core = enso_region(lat, lon)
    line = f"NOAA's Niño 3.4 anomaly was {n34:+.2f} °C in {e['latest_month']}" + (f" and the ONI {oni['value']:+.2f} °C for {oni['season']}" if oni else "") + f", {'at or beyond the +0.5 °C El Niño threshold' if state == 'El Niño' else 'at or beyond the −0.5 °C La Niña threshold' if state == 'La Niña' else 'within ±0.5 °C (neutral)'}; NOAA declares an ENSO state from persistence and the atmosphere as well, which is not assessed here."
    if abs(a) < ANOMALY_C or state == "neutral":
        return _mech("enso", name, "context", "inconclusive", None, [], [line], data, "ENSO is a basin-scale mode; it does not by itself explain a local anomaly.", "low")
    if not core:
        return _mech("enso", name, "context", "inconclusive", None, [], [line + " This place lies outside the central and eastern tropical Pacific, where ENSO acts directly; any link here would be an indirect teleconnection, which these data cannot test."], data,
                     "ENSO is a basin-scale mode; it does not by itself explain a local anomaly.", "low")
    ok = (state == "El Niño" and a > 0) or (state == "La Niña" and a < 0)
    favours = "warming" if state == "El Niño" else "cooling"
    sentence = f"This place is in the central or eastern tropical Pacific, where {state} conditions are associated with {'warm' if state == 'El Niño' else 'cold'} SST anomalies."
    return _mech("enso", name, "context", "consistent" if ok else "not consistent", favours, [line, sentence] if ok else [], [] if ok else [line + " " + sentence + f" That is the opposite sign to the {_side(a)} anomaly here."], data,
                 "ENSO is a basin-scale mode: a matching sign is context for the anomaly, not an attribution of it, and an index in a different box does not measure local processes.", "low")


FLUX_WM2 = 10.0               # judgement threshold: a bulk-estimated anomaly smaller than this is not interpreted (the estimate has not been validated against measured fluxes, so this is not an error bound)


def heat_flux_mechanism(h: dict | None, a: float, reading: dict | None, flux: dict | None = None, rad: dict | None = None) -> dict:
    name = "Air–sea heat exchange (radiation, evaporation, sensible heat)"
    data = []
    if h and h.get("available"):
        net = h["net"]
        data += [{"label": "Normal net heat flux into the ocean, first forecast day", "value": net[0], "unit": "W/m²", "period": f"{h['start_date']} (1991-2020 climatology)", "kind": "climatology"},
                 {"label": "Normal net heat flux into the ocean, 7 days later", "value": net[-1], "unit": "W/m²", "period": "1991-2020 climatology", "kind": "climatology"}]
    seasonal = None
    if h and h.get("available"):
        m = float(np.mean(h["net"]))
        seasonal = "warming" if m > 10 else "cooling" if m < -10 else None
    if not flux:
        why = (rad or {}).get("message") or ("NASA POWER radiation, the wind of the same days or the SST of the same days was not available for this place" if rad and rad.get("available") else "NASA POWER radiation was not available for this place")
        return _mech("heat_flux", name, "climatology" if data else "derived", "not assessable", seasonal, [], [], data,
                     f"Only the usual seasonal heat budget is available here ({why}); whether radiation, evaporation or sensible heat exchange explain the anomaly is unresolved.", "none")
    p = f"{rad['window']['start']} to {rad['window']['end']}"
    data += [{"label": "Net surface heat-flux anomaly (positive = more heat into the ocean)", "value": flux["net_anomaly_wm2"], "unit": "W/m²", "period": p, "kind": "derived (bulk estimate)"},
             {"label": "of which radiative (net shortwave + downward longwave)", "value": flux["radiative_part_wm2"], "unit": "W/m²", "period": p, "kind": "derived (NASA POWER)"},
             {"label": "of which upward longwave, evaporation and sensible heat (they depend on the SST, the wind and the air)", "value": flux["surface_response_wm2"], "unit": "W/m²", "period": p, "kind": "derived (bulk estimate)"},
             {"label": "Net shortwave anomaly", "value": flux["shortwave_net_wm2"], "unit": "W/m²", "period": p, "kind": "derived (NASA POWER)"},
             {"label": "Downward longwave anomaly", "value": flux["longwave_down_wm2"], "unit": "W/m²", "period": p, "kind": "derived (NASA POWER)"},
             {"label": "Evaporative (latent) heat-loss change", "value": flux["latent_loss_wm2"], "unit": "W/m²", "period": p, "kind": "derived (bulk estimate)"}]
    net, radp = flux["net_anomaly_wm2"], flux["radiative_part_wm2"]
    line = (f"Over the week to {rad['window']['end']} the net heat entering the ocean was {fr.sg(net, 0)} W/m² compared with the same week of {rad['baseline']['years'][0]}-{rad['baseline']['years'][-1]}: "
            f"radiation {fr.sg(radp, 0)} W/m² (shortwave {fr.sg(flux['shortwave_net_wm2'], 0)}, downward longwave {fr.sg(flux['longwave_down_wm2'], 0)}), and the upward-longwave, evaporative and sensible-heat terms {fr.sg(flux['surface_response_wm2'], 0)} W/m² "
            f"(evaporative loss {'higher' if flux['latent_loss_wm2'] > 0 else 'lower'} by {abs(flux['latent_loss_wm2']):.0f} W/m²).")
    cav = ("An ESTIMATE, not a measured flux: a bulk formula (neutral coefficients, fixed albedo) applied to NASA POWER analyses, CCMP winds and OISST of the same seven days, not validated against measured fluxes in this project. "
           f"The window ends {rad['dataset_end']}, before the SST date, and the upward-longwave, evaporative and sensible-heat terms depend on the SST (the ocean's reaction to the anomaly) and also on the wind and on the humidity and temperature of the air.")
    if abs(a) < ANOMALY_C or abs(net) < FLUX_WM2:
        return _mech("heat_flux", name, "derived", "inconclusive", None, [], [line + f" This is smaller than {FLUX_WM2:.0f} W/m², the size below which this estimate is not interpreted."], data, cav, "low")
    supports = (a > 0 and net > 0) or (a < 0 and net < 0)
    favours = "warming" if net > 0 else "cooling"
    radiative_supports = (a > 0 and radp >= FLUX_WM2) or (a < 0 and radp <= -FLUX_WM2)
    if supports:
        return _mech("heat_flux", name, "derived", "consistent", favours, [line], [], data, cav, "low")
    against = [line, f"The surface is {'losing' if net < 0 else 'gaining'} more heat than normal, which damps rather than builds a {_side(a)} anomaly; if the anomaly persists, other processes (reduced upwelling, ocean transport or earlier heating) must be maintaining it."]
    support = [f"The radiative part alone ({fr.sg(radp, 0)} W/m²: sunshine and cloud or humidity) did favour a {_side(a)} anomaly."] if radiative_supports else []
    return _mech("heat_flux", name, "derived", "not consistent", favours, support, against, data, cav, "low")


# ------------------------------------------------------------------------------------------------------------------------ assembling
def _series(ctx: dict, drivers: dict) -> dict | None:
    rec = ctx.get("recent") or []
    w = (drivers.get("winds") or {})
    s = (drivers.get("sea_level") or {})
    dates = sorted({r["date"] for r in rec} | {d["date"] for d in (w.get("series") or [])} | {d["date"] for d in (s.get("series") or [])})[-14:]
    if len(dates) < 3:
        return None
    idx = lambda rows, k: {r["date"]: r.get(k) for r in rows}                                # noqa: E731
    a, ws, tx, sl = idx(rec, "anomaly_c"), idx(w.get("series") or [], "speed"), idx(w.get("series") or [], "taux"), idx(s.get("series") or [], "sla_m")
    return {"dates": dates, "sst_anomaly_c": [a.get(d) for d in dates], "wind_speed_ms": [ws.get(d) for d in dates], "zonal_stress_nm2": [tx.get(d) for d in dates], "sea_level_anomaly_m": [sl.get(d) for d in dates]}


def forecast_relationship(ctx: dict, mechs: list[dict], drivers: dict) -> dict:
    rd, fc = ctx.get("reading"), ctx.get("forecast") or {}
    sst_date = _d(ctx["date"])
    lines: list[str] = []
    dates = {"sst_observation": ctx["date"], "forecast_issued_from": fc.get("issued_from"), "forecast_valid": [fc["dates"][0], fc["dates"][-1]] if fc.get("dates") else None, "drivers": {}}
    def end_of(k: str, v: dict) -> str | None:
        if k in ("sea_level", "currents"):
            return (v.get("latest") or {}).get("date")
        return v.get("latest_date") if k == "winds" else v.get("dataset_end") if k in ("enso", "radiation") else None
    for k, label in (("winds", "Winds (CCMP)"), ("radiation", "Radiation and humidity (NASA POWER)"), ("sea_level", "Sea level"), ("currents", "Currents"), ("enso", "ENSO indices"), ("heat_flux", "Heat-flux climatology")):
        v = drivers.get(k) or {}
        end = end_of(k, v)
        dates["drivers"][k] = {"label": label, "observation_date": "climatology" if k == "heat_flux" else end, "lag_days_behind_sst": _lag(sst_date, end) if (end and k not in ("enso", "heat_flux")) else None}
    if not rd:
        lines.append("No forecast is available for this place and date, so no comparison with the physical evidence is made.")
        return {"dates": dates, "statements": lines, "agreement": None}
    d = rd["label"]
    fav = [m for m in mechs if m["favours"] and m["verdict"] in ("consistent", "not consistent") and m["id"] != "enso"]
    pointing = [m for m in fav if m["verdict"] == "consistent"]
    same = [m for m in pointing if m["favours"] == {"warming": "warming", "cooling": "cooling"}.get(d)]
    opp = [m for m in pointing if d in ("warming", "cooling") and m["favours"] != d]
    lines.append(f"The ConvLSTM predicts {d} ({fr.sg(rd['sst_change_c'])} °C over {rd['days']} days) with the anomaly {fr.EXPECTED_ING[rd['anomaly_label']]} ({fr.sg(rd['anomaly_now_c'], 1)} °C to {fr.sg(rd['anomaly_end_c'], 1)} °C).")
    if d == "stable" or not pointing:
        lines.append("None of the measured indicators points clearly toward warming or cooling over the coming days, so the physical evidence neither supports nor contradicts the model trajectory.")
    elif same and not opp:
        lines.append("The indicators that are consistent with the current anomaly (" + ", ".join(m["name"].split(" (")[0].lower() for m in same) + f") also tend toward {d}; the model trajectory is directionally consistent with them.")
    elif opp and not same:
        lines.append("The indicators consistent with the current anomaly (" + ", ".join(m["name"].split(" (")[0].lower() for m in opp) + f") tend toward {'cooling' if d == 'warming' else 'warming'}, whereas the model predicts {d}: the physical evidence does not clearly agree with the model trajectory.")
    else:
        lines.append("The indicators point in different directions, so they neither confirm nor contradict the model trajectory.")
    h = drivers.get("heat_flux") or {}
    if h.get("available"):
        mean_net = float(np.mean(h["net"]))
        if abs(mean_net) >= 10:
            seas = "warming" if mean_net > 0 else "cooling"
            lines.append(f"Seasonally, the normal net heat flux over the forecast week is {mean_net:+.0f} W/m² (ocean {'gaining' if mean_net > 0 else 'losing'} heat), a {seas} tendency "
                         + ("in line with" if d == seas else "that differs from" if d in ("warming", "cooling") else "alongside") + " the predicted direction; this is climatology, not a measured flux.")
    lines.append("Agreement between these observations and the forecast does not establish causation. The ConvLSTM did not use any of these variables, and its sensitivity analysis describes the model, not the ocean.")
    lines.append(f"The physical indicators describe the latest observations (up to {max([v['observation_date'] for v in dates['drivers'].values() if v['observation_date'] and v['observation_date'] != 'climatology'] or [ctx['date']])}); "
                 "they are not forecasts of winds, currents or fluxes, and no forecast of them is available here.")
    return {"dates": dates, "statements": lines, "agreement": "directionally consistent" if (same and not opp) else "not clearly consistent" if (opp and not same) else "indeterminate"}


FAMILY = {"wind": "wind field (CCMP)", "upwelling": "wind field (CCMP)", "sea_level": "satellite altimetry", "advection": "satellite altimetry", "heat_flux": "surface radiation and humidity (NASA POWER)"}


def confidence(mechs: list[dict], a: float) -> dict:
    """Evidence strength counts independent DATA FAMILIES, not indicators: wind and upwelling both come from the same wind field, so they are one line of evidence."""
    measured = [m for m in mechs if m["id"] in FAMILY and m["verdict"] in ("consistent", "not consistent")]
    yes = {FAMILY[m["id"]] for m in measured if m["verdict"] == "consistent"}
    no = {FAMILY[m["id"]] for m in measured if m["verdict"] == "not consistent"}
    n_na = sum(1 for m in mechs if m["verdict"] == "not assessable")
    if abs(a) < ANOMALY_C:
        level, text = "not applicable", "The SST anomaly is small, so there is no anomaly to attribute."
    elif not measured:
        level, text = "limited", "None of the measured or derived indicators could be assessed against this anomaly, or all were within their normal range."
    elif yes and no:
        both = yes & no
        pro, con = sorted(yes - no), sorted(no - yes)
        parts = ([f"evidence from {', '.join(pro)} is consistent with the anomaly"] if pro else []) + ([f"evidence from {', '.join(con)} is not"] if con else []) +                 ([f"within {', '.join(sorted(both))} one indicator is consistent and another is not"] if both else [])
        level, text = "mixed", f"{'; '.join(parts)[:1].upper() + '; '.join(parts)[1:]}: the indicators conflict, so no single mechanism is favoured."
    elif len(yes) >= 2:
        level, text = "moderate (plausible mechanisms)", f"{len(yes)} independent lines of evidence ({', '.join(sorted(yes))}) are consistent with the anomaly and none contradicts it. This supports plausible mechanisms; it is not attribution."
    elif len(yes) == 1:
        level, text = "limited", f"Only one line of evidence ({next(iter(yes))}) is consistent with the anomaly, so the interpretation rests on a single data source."
    else:
        level, text = "limited", f"The assessable indicators ({', '.join(sorted(no))}) argue against the mechanisms tested; the cause of the anomaly remains unresolved by these data."
    return {"level": level, "text": text + (f" {n_na} mechanism(s) could not be assessed with the available data." if n_na else ""), "attribution": "No causal attribution is made."}


def analyse(drivers: dict, ctx: dict) -> dict:
    a = ctx["anomaly"]
    w, cur, sl, en, hf = drivers.get("winds"), drivers.get("currents"), drivers.get("sea_level"), drivers.get("enso"), drivers.get("heat_flux")
    trend = (ctx.get("trends") or {}).get("sst_7d_c_per_day")
    rad = drivers.get("radiation")
    ws = ctx.get("window_sst")                                                               # SST and its normal over the radiation days, so that all inputs describe the same week
    flux = pdv.bulk_flux_anomaly(rad, (rad or {}).get("wind_window"), ws["sst"] if ws else None, ws["normal"] if ws else None)
    mechs = [wind_mechanism(w, a), heat_flux_mechanism(hf, a, ctx.get("reading"), flux, rad), advection_mechanism(cur, ctx.get("advection"), trend, ctx["lat"], a),
             upwelling_mechanism(w, a, ctx["lat"], ctx.get("coast")), sea_level_mechanism(sl, a), enso_mechanism(en, a, ctx["lat"], ctx["lon"])]
    sst_date = _d(ctx["date"])
    sources = []
    for key, label in (("winds", "Wind and wind stress"), ("radiation", "Surface radiation and humidity (NASA POWER)"), ("heat_flux", "Surface heat flux (climatology)"), ("sea_level", "Sea level anomaly"), ("currents", "Surface currents"), ("enso", "ENSO indices")):
        v = drivers.get(key) or {}
        st = (drivers.get("sources") or {}).get(key, {"status": "unavailable"})
        end = v.get("dataset_end")
        used = {"winds": v.get("latest_date"), "sea_level": (v.get("latest") or {}).get("date"), "currents": (v.get("latest") or {}).get("date"), "radiation": end}.get(key)      # the day actually used
        lag_from = used or end
        lag = _lag(sst_date, lag_from) if lag_from and key != "heat_flux" and len(str(lag_from)) >= 10 else None
        status = st.get("status", "unavailable")
        if status == "ok" and lag is not None and lag > 45 and key != "enso":
            status = "stale"
        sources.append({"id": key, "label": label, "status": status, "source": v.get("source"), "dataset": v.get("dataset"), "variable": v.get("variable"), "unit": v.get("unit"), "kind": v.get("kind"),
                        "spatial_resolution": v.get("spatial_resolution"), "temporal_resolution": v.get("temporal_resolution"), "dataset_end": end, "used_through": used if key not in ("heat_flux", "enso") else None, "lag_days_behind_sst": lag, "retrieved": v.get("retrieved"),
                        "message": v.get("message") or st.get("message"), "caveat": v.get("caveat")})
    obs = {"date": ctx["date"], "sst_c": ctx["sst"], "anomaly_c": a, "classification": fr.classify_anomaly(a), "trends": ctx.get("trends"),
           "text": f"On {ctx['date']} sea surface temperature at this place is {ctx['sst']:.1f} °C, {fr.sg(a, 1)} °C relative to its {'seasonal baseline' if ctx.get('baseline') is None else ctx['baseline']}"
                   + (f"; over the last {ctx['trends']['days']} days SST changed at {fr.sg(ctx['trends']['sst_7d_c_per_day'], 3)} °C/day and the anomaly by {fr.sg(ctx['trends']['anomaly_7d_change_c'], 2)} °C." if ctx.get("trends") else ".")}
    return {"available": True, "observed": obs, "mechanisms": mechs, "forecast_relationship": forecast_relationship(ctx, mechs, drivers), "confidence": confidence(mechs, a), "series": _series(ctx, drivers),
            "sources": sources, "flux": flux, "method": METHOD, "status": drivers.get("status"),
            "definitions": {"observed anomaly": "a measured departure of SST from its seasonal normal", "plausible mechanism": "a physical process whose measured indicator moves the way that would produce this anomaly",
                            "verified causal attribution": "a demonstration, by budget closure or experiment, that a process produced the anomaly; not provided by this analysis"},
            "limitations": ["Consistency of an indicator with an anomaly is evidence for a plausible mechanism, not proof of cause.", "Indicators are 7-day means at 0.25° (flux climatology at about 1.9°); processes shorter or smaller than that are not resolved.",
                            "Wind-driven currents, vertical mixing, salinity and subsurface temperature are not measured here.",
                            "The surface heat-flux anomaly is a bulk estimate that has not been validated against measured fluxes; it is not a measurement.",
                            "Spatial scales differ: OISST is point-sampled at 1°, winds, sea level and currents are 0.25° (winds averaged over 3 × 3 cells), NASA POWER radiation is a 1° × 1° cell value (CERES) and its air temperature and humidity are 0.5° × 0.625° (MERRA-2); a place on a 1° cell boundary can fall in either cell, and adjacent cells can differ strongly on a single day. The flux climatology is about 1.9°.",
                            "Sources have different latest days (the table gives the day each value actually used); the SST anomaly of the last day is compared with indicators of earlier days."]}
