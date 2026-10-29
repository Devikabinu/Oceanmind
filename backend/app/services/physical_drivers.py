"""Measured physical context for a place, from sources whose variables, dates and coverage were checked before use (see docs/PLATFORM.md section 5.6):

  winds        CCMP v2.1 near-real-time 10 m wind (RSS; NOAA PIFSC ERDDAP `ccmp-daily-v2-1-NRT`), 6-hourly, 0.25 deg, 2015-present. Wind speed and wind stress (derived with the Large and Pond
               bulk formula), recent seven days against the same seven days of 2016-2025.
  heat flux    NCEP/NCAR Reanalysis 1 surface fluxes, 1991-2020 daily CLIMATOLOGY only (NOAA PSL THREDDS). The reanalysis files themselves end in March 2026, so no current flux is claimed.
  sea level    NOAA blended altimetry sea level anomaly (CoastWatch ERDDAP `noaacwBLENDEDsshDaily`), daily, 0.25 deg.
  currents     NOAA blended altimetry geostrophic currents (CoastWatch `noaacwBLENDEDNRTcurrentsDaily`), daily, 0.25 deg (shared with the ocean-context service).
  ENSO         NOAA Climate Prediction Center Nino indices (`sstoi.indices`) and the Oceanic Nino Index.

Every source is fetched on its own and carries its own status, last observation date and lag; one source failing leaves the others in place. Nothing is interpolated or filled in:
a missing period stays missing and the source is reported as unavailable or stale. Results are cached on disk (current data 12 hours, baselines 90 days) and fetched in the background
so that a click never waits for the network."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

from app.services import ocean_context as oc

log = logging.getLogger("ocean_platform")

ENABLED = True                         # switched off by the test configuration
SCHEMA = 2
TTL = timedelta(hours=12)
BASELINE_TTL = timedelta(days=90)
RETRY_AFTER = timedelta(minutes=10)
CCMP = "ccmp-daily-v2-1-NRT"
SSH = "noaacwBLENDEDsshDaily"
PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets/ncep.reanalysis.derived/surface_gauss"
CPC = "https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices"
RHO_AIR, RHO_WATER, OMEGA = 1.22, 1025.0, 7.2921e-5
BASELINE_YEARS = 10
MIN_BASELINE_YEARS = 6
RECENT_DAYS = 7

_inflight: dict[str, threading.Thread] = {}
_failed: dict[str, datetime] = {}
_mutex = threading.Lock()
_grid_cache: dict = {}


def cache_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "cache" / "physical_drivers"


def _file(key: str) -> Path:
    return cache_dir() / f"phys_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


def _load(key: str) -> dict | None:
    try:
        return json.loads(_file(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(key: str, payload: dict) -> None:
    f = _file(key)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(f)


def _key(lat: float, lon: float) -> str:
    return f"v{SCHEMA}_{round(lat * 4) / 4:+.2f}_{round(((lon + 180) % 360 - 180) * 4) / 4:+.2f}"


def lon360(lon: float) -> float:
    return lon % 360.0


def lon180(lon: float) -> float:
    return ((lon + 180.0) % 360.0) - 180.0


# ---------------------------------------------------------------------------------------------------- wind stress and Ekman transport
def drag_coefficient(u10: float) -> float:
    """Neutral 10 m drag coefficient of Large and Pond (1981): 1.2e-3 below 11 m/s, then rising linearly (capped at 25 m/s)."""
    u = min(u10, 25.0)
    return 1.2e-3 if u < 11.0 else (0.49 + 0.065 * u) * 1e-3


def wind_stress(u: float, v: float) -> tuple[float, float]:
    """(tau_x, tau_y) in N/m^2 from the 10 m wind (m/s): tau = rho_air * Cd * |U| * (u, v). Derived, not measured."""
    s = math.hypot(u, v)
    k = RHO_AIR * drag_coefficient(s) * s
    return k * u, k * v


def ekman_transport(lat: float, taux: float, tauy: float) -> tuple[float, float] | None:
    """Ekman volume transport per metre of width (m^2/s): (tau_y, -tau_x) / (rho_w f). Not defined close to the equator, where f is near zero."""
    if abs(lat) < 3.0:
        return None
    f = 2 * OMEGA * math.sin(math.radians(lat))
    return tauy / (RHO_WATER * f), -taux / (RHO_WATER * f)


def bearing_from(u: float, v: float) -> float:
    """Meteorological direction the wind blows FROM, in degrees clockwise from north."""
    return (math.degrees(math.atan2(-u, -v)) + 360.0) % 360.0


# ---------------------------------------------------------------------------------------------------- winds
def _time_rows(rows: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """{iso time: [(u, v), ...]} over the cells of the window; cells without a value are left out."""
    out: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        u, v = oc._num(r["uwnd"]), oc._num(r["vwnd"])
        if np.isfinite(u) and np.isfinite(v):
            out.setdefault(r["time"], []).append((u, v))
    return out


def _daily(by_time: dict[str, list[tuple[float, float]]]) -> list[dict]:
    """Daily means (UTC) of speed, stress and the wind vector; a day needs at least three of its four 6-hourly analyses."""
    days: dict[str, list[tuple[float, float, float, float, float]]] = {}
    for t, cells in sorted(by_time.items()):
        u, v = float(np.mean([c[0] for c in cells])), float(np.mean([c[1] for c in cells]))
        tx, ty = wind_stress(u, v)
        days.setdefault(t[:10], []).append((math.hypot(u, v), u, v, tx, ty))
    return [{"date": d, "speed": round(float(np.mean([x[0] for x in v])), 3), "u": round(float(np.mean([x[1] for x in v])), 3), "v": round(float(np.mean([x[2] for x in v])), 3),
             "taux": round(float(np.mean([x[3] for x in v])), 5), "tauy": round(float(np.mean([x[4] for x in v])), 5)} for d, v in days.items() if len(v) >= 3]


def _wind_query(lat: float, lon: float, t0: str, t1: str) -> list[dict]:
    a0, a1, o0, o1 = lat - 0.25, lat + 0.25, lon360(lon) - 0.25, lon360(lon) + 0.25
    rng = f"%5B({t0}):1:({t1})%5D%5B({a0:.4f}):1:({a1:.4f})%5D%5B({o0:.4f}):1:({o1:.4f})%5D"
    return _daily(_time_rows(oc._csv(f"{oc.PIFSC}/{CCMP}.csv?uwnd{rng},vwnd{rng}")))


def _wind_baseline(lat: float, lon: float, end: datetime) -> dict:
    """Mean and standard deviation, over the previous ten years, of the seven-day mean wind speed and stress ending on the same calendar day."""
    key = f"wbase_{_key(lat, lon)}_{end.strftime('%m%d')}"
    cached = _load(key)
    if cached and datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"]) < BASELINE_TTL:
        return cached

    def one(year: int):
        try:
            e = end.replace(year=year)
        except ValueError:                                                      # 29 February
            e = end.replace(year=year, day=28)
        s = e - timedelta(days=RECENT_DAYS - 1)
        days = _wind_query(lat, lon, s.strftime("%Y-%m-%dT00:00:00Z"), e.strftime("%Y-%m-%dT18:00:00Z"))
        if len(days) < RECENT_DAYS - 1:
            return None
        return {k: float(np.mean([d[k] for d in days])) for k in ("speed", "u", "v", "taux", "tauy")} | {"year": year}
    years = [y for y in range(end.year - BASELINE_YEARS, end.year) if y >= 2016]
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = [g for g in ex.map(one, years) if g]
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "years": [g["year"] for g in got], "window": f"the {RECENT_DAYS} days ending {end.strftime('%d %B')}",
           "dataset": f"{CCMP} (CCMP v2.1 near-real-time winds)"}
    if len(got) >= MIN_BASELINE_YEARS:
        for k in ("speed", "u", "v", "taux", "tauy"):
            vals = np.array([g[k] for g in got])
            out[k] = {"mean": round(float(vals.mean()), 5), "sd": round(float(vals.std(ddof=1)), 5)}
        _save(key, out)
    else:
        out["insufficient"] = f"only {len(got)} of {len(years)} baseline years had complete data"
    return out


def winds(lat: float, lon: float) -> dict:
    last = oc._csv(f"{oc.PIFSC}/{CCMP}.csv?time%5B(last)%5D")[0]["time"]
    end = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ")
    t0 = (end - timedelta(days=2 * RECENT_DAYS - 1)).strftime("%Y-%m-%dT00:00:00Z")
    days = _wind_query(lat, lon, t0, last)
    base = {"source": "RSS CCMP v2.1 near-real-time winds (NOAA PIFSC ERDDAP)", "dataset": f"{CCMP}", "variable": "10 m wind (u, v)", "unit": "m/s", "stress_unit": "N/m²",
            "spatial_resolution": "0.25° (mean of the cells within ±0.25°)", "temporal_resolution": "6-hourly analyses, averaged to UTC days", "dataset_end": end.date().isoformat(), "kind": "measurement (analysis) and derived stress"}
    if len(days) < RECENT_DAYS:
        return {**base, "available": False, "message": f"Fewer than {RECENT_DAYS} complete days of wind analysis at this place in the 14 days to {end.date().isoformat()}."}
    recent, prev = days[-RECENT_DAYS:], days[-2 * RECENT_DAYS:-RECENT_DAYS]
    m = lambda rows, k: float(np.mean([r[k] for r in rows]))                        # noqa: E731
    cur = {k: m(recent, k) for k in ("speed", "u", "v", "taux", "tauy")}
    out = {**base, "available": True, "latest_date": recent[-1]["date"], "window": {"start": recent[0]["date"], "end": recent[-1]["date"]}, "series": days,
           "recent": {k: round(v, 4) for k, v in cur.items()} | {"direction_from_deg": round(bearing_from(cur["u"], cur["v"]))},
           "previous": {k: round(m(prev, k), 4) for k in ("speed", "taux", "tauy")} if len(prev) >= RECENT_DAYS - 1 else None}
    used_end = datetime.strptime(recent[-1]["date"], "%Y-%m-%d") + timedelta(hours=18)           # the baseline ends on the last COMPLETE day used, not on the last analysis time
    b = _wind_baseline(lat, lon, used_end)
    if "speed" in b:
        out["baseline"] = {"years": b["years"], "window": b["window"], "dataset": b["dataset"], **{k: b[k] for k in ("speed", "u", "v", "taux", "tauy")}}
        z = lambda k: None if b[k]["sd"] <= 0 else round((cur[k] - b[k]["mean"]) / b[k]["sd"], 2)       # noqa: E731
        out["anomaly"] = {"speed": round(cur["speed"] - b["speed"]["mean"], 3), "speed_z": z("speed"), "taux": round(cur["taux"] - b["taux"]["mean"], 5), "taux_z": z("taux"),
                          "tauy": round(cur["tauy"] - b["tauy"]["mean"], 5), "tauy_z": z("tauy")}
    else:
        out["baseline_message"] = b.get("insufficient", "no baseline")
    return out


# ---------------------------------------------------------------------------------------------------- heat flux climatology (NCEP/NCAR Reanalysis 1, 1991-2020)
_dap_lock = threading.Lock()
_dap_last = [0.0]
DAP_SPACING_S = 0.5                    # NOAA PSL answers HTTP 429 to bursts: its requests are made one at a time, with a pause between them


def _dap(url: str) -> str:
    last = None
    for attempt in range(5):
        with _dap_lock:
            wait = DAP_SPACING_S - (time.monotonic() - _dap_last[0])
            if wait > 0:
                time.sleep(wait)
            try:
                r = requests.get(url, timeout=oc.TIMEOUT, headers={"User-Agent": "OceanMind/1.0 (research dashboard)"})
            except requests.RequestException as exc:
                r, last = None, exc.__class__.__name__
            _dap_last[0] = time.monotonic()
        if r is not None:
            if r.status_code == 200:
                return r.text
            last = f"HTTP {r.status_code}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
            try:
                pause = float(r.headers.get("Retry-After", 0))
            except ValueError:
                pause = 0.0
        else:
            pause = 0.0
        time.sleep(min(max(pause, 2.0 ** attempt), 20.0))
    raise RuntimeError(f"OPeNDAP request failed ({last})")


def _dap_axis(f: str, name: str) -> np.ndarray:
    key = (f, name)
    if key not in _grid_cache:
        body = _dap(f"{PSL}/{f}.ascii?{name}").split(f"{name}[", 1)[1].split("\n", 1)[1]
        _grid_cache[key] = np.array([float(x) for x in re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", body)])
    return _grid_cache[key]


def _dap_values(txt: str, var: str) -> list[float]:
    block = txt.split(f"{var}.{var}[", 1)[1].split("\n", 1)[1].split("\n\n", 1)[0]
    return [float(v) for line in block.splitlines() for v in line.split(",")[1:] if v.strip()]


def _doy_index(d: date) -> int:
    return (date(2001, 2, 28) if (d.month, d.day) == (2, 29) else d.replace(year=2001)).timetuple().tm_yday - 1


def heat_flux_climatology(lat: float, lon: float, d: date, days: int = 8) -> dict:
    """Net surface heat flux into the ocean, 1991-2020 daily climatology of NCEP/NCAR Reanalysis 1, for `days` days from `d` at the nearest reanalysis grid point. This is what is NORMAL for the date,
    not an observation of this year: the reanalysis files of 2026 end in March 2026 and are not used."""
    comps = {"dswrf": +1, "uswrf": -1, "dlwrf": +1, "ulwrf": -1, "lhtfl": -1, "shtfl": -1}
    names = {v: f"{v}.sfc.gauss.day.ltm.1991-2020.nc" for v in comps}
    f0 = names["lhtfl"]
    la, lo = _dap_axis(f0, "lat"), _dap_axis(f0, "lon")
    i, j = int(np.abs(la - lat).argmin()), int(np.abs(lo - lon360(lon)).argmin())
    t0 = _doy_index(d)
    idx = [(_doy_index(d + timedelta(days=k))) for k in range(days)]
    runs: list[tuple[int, int]] = []                                            # contiguous runs of day-of-year indices: a window across the new year is fetched in two pieces
    for k in idx:
        if runs and k == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], k)
        else:
            runs.append((k, k))
    vals: dict[str, list[float]] = {}
    for v in comps:
        vals[v] = [x for a, b in runs for x in _dap_values(_dap(f"{PSL}/{names[v]}.ascii?{v}[{a}:1:{b}][{i}:1:{i}][{j}:1:{j}]"), v)]
        if len(vals[v]) != days:
            raise RuntimeError(f"climatology of {v} has {len(vals[v])} values, expected {days}")
    net = [sum(comps[v] * vals[v][k] for v in comps) for k in range(days)]
    return {"available": True, "source": "NOAA PSL, NCEP/NCAR Reanalysis 1 (Kalnay et al. 1996)", "dataset": "surface_gauss fluxes, daily long-term mean 1991-2020", "kind": "climatology (not an observation of this year)",
            "unit": "W/m²", "sign": "positive = heat gained by the ocean (net = shortwave down − up + longwave down − up − latent − sensible)", "spatial_resolution": "T62 Gaussian grid, about 1.9°",
            "temporal_resolution": "daily climatology", "grid_point": {"lat": round(float(la[i]), 2), "lon": round(lon180(float(lo[j])), 2)}, "start_date": d.isoformat(),
            "net": [round(x, 1) for x in net], "components_first_day": {k: round(vals[k][0], 1) for k in vals},
            "text": f"On this date, over 1991-2020, the reanalysis climatology has the ocean {'gaining' if net[0] > 0 else 'losing'} about {abs(net[0]):.0f} W/m² on average through the surface "
                    f"(shortwave and longwave radiation less latent and sensible heat loss), and {'gaining' if net[-1] > 0 else 'losing'} {abs(net[-1]):.0f} W/m² {days - 1} days later. "
                    "This is the usual seasonal heat budget, not this year's flux.",
            "caveat": "Reanalysis surface fluxes are model products with biases that are not quantified here; they are used only as the normal seasonal budget, never as this year's flux.",
            "dataset_end": "climatology (no end date)"}


# ---------------------------------------------------------------------------------------------------- sea level anomaly
def _sla_rows(lat: float, lon: float, t0: str, t1: str) -> dict[str, float]:
    a0, a1, o0, o1 = lat - 0.125, lat + 0.125, lon180(lon) - 0.125, lon180(lon) + 0.125
    rows = oc._csv(f"{oc.COASTWATCH}/{SSH}.csv?sla%5B({t0}):1:({t1})%5D%5B({a0:.4f}):1:({a1:.4f})%5D%5B({o0:.4f}):1:({o1:.4f})%5D")
    by: dict[str, list[float]] = {}
    for r in rows:
        v = oc._num(r["sla"])
        if np.isfinite(v):
            by.setdefault(r["time"][:10], []).append(v)
    return {d: float(np.mean(v)) for d, v in sorted(by.items())}


def _sla_baseline(lat: float, lon: float, end: date) -> dict:
    """Mean and standard deviation, over 2016-2025, of the 7-calendar-day mean sea level anomaly ending on the same calendar day. The product is referenced to a long-term mean sea surface and still
    contains the seasonal cycle of sea level, so only a departure from the same days of other years says anything about this year."""
    key = f"slabase_{_key(lat, lon)}_{end.strftime('%m%d')}"
    cached = _load(key)
    if cached and datetime.now(timezone.utc) - datetime.fromisoformat(cached["fetched_at"]) < BASELINE_TTL:
        return cached

    def one(year: int):
        try:
            e = end.replace(year=year)
        except ValueError:
            e = end.replace(year=year, day=28)
        try:
            days = _sla_rows(lat, lon, f"{(e - timedelta(days=RECENT_DAYS - 1)).isoformat()}T00:00:00Z", f"{e.isoformat()}T00:00:00Z")
        except RuntimeError:
            return None
        return {"year": year, "mean": float(np.mean(list(days.values())))} if len(days) >= 4 else None
    years = [y for y in range(2016, end.year)]
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = [g for g in ex.map(one, years) if g]
    out = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "years": [g["year"] for g in got]}
    if len(got) >= MIN_BASELINE_YEARS:
        vals = np.array([g["mean"] for g in got])
        out.update(mean=round(float(vals.mean()), 5), sd=round(float(vals.std(ddof=1)), 5))
        _save(key, out)
    else:
        out["insufficient"] = f"only {len(got)} of {len(years)} baseline years had at least 4 valid days"
    return out


def sea_level(lat: float, lon: float) -> dict:
    end = oc._last_time(oc.COASTWATCH, SSH)
    start = end - timedelta(days=29)
    by = _sla_rows(lat, lon, start.isoformat(), end.isoformat())
    series = [{"date": d, "sla_m": round(v, 4)} for d, v in by.items()]
    base = {"source": "NOAA CoastWatch (NESDIS/STAR) blended altimetry", "dataset": f"{SSH} (sea level anomaly)", "variable": "sea level anomaly", "unit": "m", "spatial_resolution": "0.25°",
            "temporal_resolution": "daily", "dataset_end": end.isoformat(), "kind": "measurement (altimetry, relative to the DTU15 long-term mean sea surface; the seasonal cycle is not removed)"}
    if len(series) < 10:
        return {**base, "available": False, "message": f"Fewer than 10 days of valid sea level anomaly at this place in the 30 days to {end.isoformat()} (land, coast or no coverage)."}
    latest = date.fromisoformat(series[-1]["date"])
    recent = [s["sla_m"] for s in series if (latest - date.fromisoformat(s["date"])).days < RECENT_DAYS]          # the 7 calendar days to the last valid day
    earlier = [s["sla_m"] for s in series if (latest - date.fromisoformat(s["date"])).days >= RECENT_DAYS]
    if len(recent) < 4:
        return {**base, "available": False, "message": f"Fewer than 4 valid sea level days in the 7 days to {latest.isoformat()} at this place."}
    out = {**base, "available": True, "latest": series[-1], "recent_mean_m": round(float(np.mean(recent)), 4), "recent_days": len(recent), "window": {"start": (latest - timedelta(days=RECENT_DAYS - 1)).isoformat(), "end": latest.isoformat()},
           "earlier_mean_m": round(float(np.mean(earlier)), 4) if earlier else None, "change_m": None if not earlier else round(float(np.mean(recent) - np.mean(earlier)), 4), "series": series[-14:], "valid_days": len(series)}
    try:
        b = _sla_baseline(lat, lon, latest)
    except Exception as exc:  # noqa: BLE001 - the baseline is optional; without it the departure is simply not given
        b = {"insufficient": f"the same-week baseline could not be retrieved ({exc.__class__.__name__})"}
    if "mean" in b:
        out["baseline"] = {"years": b["years"], "mean_m": b["mean"], "sd_m": b["sd"]}
        out["departure_m"] = round(out["recent_mean_m"] - b["mean"], 4)
        out["departure_z"] = None if b["sd"] <= 0 else round((out["recent_mean_m"] - b["mean"]) / b["sd"], 2)
    else:
        out["baseline_message"] = b.get("insufficient", "no baseline")
    return out


# ---------------------------------------------------------------------------------------------------- surface radiation and humidity (NASA POWER) and the bulk heat-flux anomaly
POWER = "https://power.larc.nasa.gov/api/temporal/daily/point"
POWER_PARAMS = "ALLSKY_SFC_SW_DWN,ALLSKY_SFC_LW_DWN,T2M,QV2M,PS"
WM2_PER_KWH_DAY = 1000.0 / 24.0               # POWER gives radiation in kW-hr/m^2/day
POWER_FILL = -999.0
ALBEDO = 0.06                                  # open-ocean shortwave albedo (typical value; not measured here)
CE = CH = 1.2e-3                               # neutral bulk transfer coefficients for latent and sensible heat
LV, CP_AIR = 2.5e6, 1005.0


def _power_json(lat: float, lon: float, start: str, end: str) -> dict:
    last = None
    for _ in range(3):
        try:
            r = requests.get(POWER, params={"parameters": POWER_PARAMS, "community": "RE", "longitude": round(lon180(lon), 4), "latitude": round(lat, 4), "start": start, "end": end, "format": "JSON"},
                             timeout=(5, 40), headers={"User-Agent": "OceanMind/1.0 (research dashboard)"})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 422):
                break
        except (requests.RequestException, ValueError) as exc:
            last = exc.__class__.__name__
    raise RuntimeError(f"NASA POWER request failed ({last})")


def _power_days(d: dict) -> dict[str, dict]:
    """{YYYY-MM-DD: {sw, lw (W/m^2), t2m (C), q (g/kg), ps (kPa)}} for the days where every variable has a value; a fill value (-999) is a missing day, never a number."""
    p = d["properties"]["parameter"]
    out = {}
    for k, sw in p["ALLSKY_SFC_SW_DWN"].items():
        vals = [sw, p["ALLSKY_SFC_LW_DWN"].get(k), p["T2M"].get(k), p["QV2M"].get(k), p["PS"].get(k)]
        if any(v is None or v == POWER_FILL or not np.isfinite(v) for v in vals):
            continue
        out[f"{k[:4]}-{k[4:6]}-{k[6:]}"] = {"sw": sw * WM2_PER_KWH_DAY, "lw": vals[1] * WM2_PER_KWH_DAY, "t2m": vals[2], "q": vals[3], "ps": vals[4]}
    return out


def _window(days: dict[str, dict], end: date, n: int) -> list[dict]:
    rows = [days.get((end - timedelta(days=k)).isoformat()) for k in range(n)]
    return [r for r in rows if r]


def power_met(lat: float, lon: float, today: date | None = None) -> dict:
    """The last seven days of surface shortwave and longwave radiation, 2 m air temperature, humidity and pressure at the place, against the same seven days of 2016-2025."""
    today = today or date.today()
    days = _power_days(_power_json(lat, lon, "20160101", today.strftime("%Y%m%d")))
    base = {"source": "NASA POWER (MERRA-2 and CERES-based surface meteorology and solar radiation)", "dataset": "POWER daily point API v2.10 (ALLSKY_SFC_SW_DWN, ALLSKY_SFC_LW_DWN, T2M, QV2M, PS)",
            "unit": "W/m² (radiation), °C, g/kg, kPa", "spatial_resolution": "radiation 1° × 1° (CERES), air temperature, humidity and pressure 0.5° × 0.625° (MERRA-2); the value of the grid cell that contains the point", "temporal_resolution": "daily", "kind": "analysis (satellite- and model-based), not in-situ"}
    if not days:
        return {**base, "available": False, "message": "NASA POWER returned no valid days for this place."}
    end = date.fromisoformat(max(days))
    rec = _window(days, end, RECENT_DAYS)
    if len(rec) < RECENT_DAYS - 1:
        return {**base, "available": False, "dataset_end": end.isoformat(), "message": f"Fewer than {RECENT_DAYS - 1} valid days of NASA POWER radiation in the week to {end.isoformat()}."}
    mean = lambda rows, k: float(np.mean([r[k] for r in rows]))                                    # noqa: E731
    cur = {k: mean(rec, k) for k in ("sw", "lw", "t2m", "q", "ps")}
    years = []
    for y in range(2016, end.year):
        try:
            e = end.replace(year=y)
        except ValueError:
            e = end.replace(year=y, day=28)
        w = _window(days, e, RECENT_DAYS)
        if len(w) >= RECENT_DAYS - 1:
            years.append({"year": y, **{k: mean(w, k) for k in ("sw", "lw", "t2m", "q", "ps")}})
    out = {**base, "available": True, "dataset_end": end.isoformat(), "window": {"start": (end - timedelta(days=RECENT_DAYS - 1)).isoformat(), "end": end.isoformat()},
           "valid_days": len(rec), "recent": {k: round(v, 3) for k, v in cur.items()}}
    if len(years) >= MIN_BASELINE_YEARS:
        out["baseline"] = {"years": [y["year"] for y in years], **{k: {"mean": round(float(np.mean([y[k] for y in years])), 3), "sd": round(float(np.std([y[k] for y in years], ddof=1)), 3)} for k in ("sw", "lw", "t2m", "q", "ps")}}
        out["anomaly"] = {k: round(cur[k] - out["baseline"][k]["mean"], 3) for k in ("sw", "lw", "t2m", "q")}
    else:
        out["baseline_message"] = f"only {len(years)} baseline years had complete data"
    return out


def wind_window(lat: float, lon: float, end: date) -> dict | None:
    """The CCMP wind speed over the SAME seven days as the radiation window (not the CCMP week, which ends later), with the same days of 2016-2025 as its reference. None when the
    wind of those days is not available."""
    s0 = end - timedelta(days=RECENT_DAYS - 1)
    days = [d for d in _wind_query(lat, lon, f"{s0.isoformat()}T00:00:00Z", f"{end.isoformat()}T18:00:00Z") if s0.isoformat() <= d["date"] <= end.isoformat()]
    if len(days) < RECENT_DAYS - 2:
        return None
    b = _wind_baseline(lat, lon, datetime(end.year, end.month, end.day, 18))
    if "speed" not in b:
        return None
    return {"available": True, "window": {"start": days[0]["date"], "end": days[-1]["date"]}, "valid_days": len(days), "recent": {"speed": float(np.mean([d["speed"] for d in days]))},
            "baseline": {"speed": b["speed"], "years": b["years"]}}


def _qsat(t_c: float, p_hpa: float) -> float:
    es = 6.1094 * math.exp(17.625 * t_c / (t_c + 243.04))
    return 0.622 * es / (p_hpa - 0.378 * es)


def _bulk(sst_c: float, u: float, t2m: float, q_gkg: float, ps_kpa: float) -> tuple[float, float]:
    """(latent, sensible) heat LOSS in W/m^2 by the neutral bulk formulas: LH = rho Lv Ce U (0.98 q_sat(SST) - q_a), SH = rho cp Ch U (SST - T_air)."""
    p_hpa = ps_kpa * 10.0
    qa = q_gkg / 1000.0
    rho = ps_kpa * 1000.0 / (287.05 * (t2m + 273.15) * (1 + 0.608 * qa))
    lh = rho * LV * CE * u * (0.98 * _qsat(sst_c, p_hpa) - qa)
    sh = rho * CP_AIR * CH * u * (sst_c - t2m)
    return lh, sh


def _lw_up(t_c: float) -> float:
    return 0.97 * 5.670374e-8 * (t_c + 273.15) ** 4


def bulk_flux_anomaly(power: dict | None, winds: dict | None, sst_c: float | None, sst_normal_c: float | None) -> dict | None:
    """The anomaly of the net heat flux INTO the ocean: the last week (observed atmosphere over the observed SST) minus the same week of 2016-2025 (normal atmosphere over the NORMAL SST). Positive = more
    heat entering than usual. Its upward-longwave, evaporative and sensible-heat terms depend on the SST (a warm SST loses more heat), the wind and the air's humidity and temperature, so over a warm anomaly the total is often negative
    (the surface is damping the anomaly). The radiative part (shortwave + downward longwave) is reported on its own because it does not depend on the SST. A bulk estimate with stated assumptions,
    not a measured flux, and not validated against measured fluxes in this project (no error bound is claimed)."""
    ok = (power and power.get("available") and "baseline" in power and winds and winds.get("available") and "baseline" in winds and sst_c is not None and sst_normal_c is not None
          and np.isfinite(sst_c) and np.isfinite(sst_normal_c))
    if not ok:
        return None
    r, b = power["recent"], power["baseline"]
    u_rec, u_base = winds["recent"]["speed"], winds["baseline"]["speed"]["mean"]
    lh_r, sh_r = _bulk(sst_c, u_rec, r["t2m"], r["q"], r["ps"])
    lh_b, sh_b = _bulk(sst_normal_c, u_base, b["t2m"]["mean"], b["q"]["mean"], b["ps"]["mean"])
    d_sw = (1 - ALBEDO) * (r["sw"] - b["sw"]["mean"])
    d_lwd = r["lw"] - b["lw"]["mean"]
    d_lwu, d_lh, d_sh = _lw_up(sst_c) - _lw_up(sst_normal_c), lh_r - lh_b, sh_r - sh_b
    net = d_sw + d_lwd - d_lwu - d_lh - d_sh
    return {"net_anomaly_wm2": round(net, 1), "radiative_part_wm2": round(d_sw + d_lwd, 1), "shortwave_net_wm2": round(d_sw, 1), "longwave_down_wm2": round(d_lwd, 1),
            "longwave_up_wm2": round(d_lwu, 1), "latent_loss_wm2": round(d_lh, 1), "sensible_loss_wm2": round(d_sh, 1), "surface_response_wm2": round(-(d_lwu + d_lh + d_sh), 1),
            "latent_recent_wm2": round(lh_r, 1), "latent_baseline_wm2": round(lh_b, 1), "sst_c": round(float(sst_c), 2), "sst_normal_c": round(float(sst_normal_c), 2),
            "assumptions": [f"observed SST {sst_c:.1f} °C against the normal SST {sst_normal_c:.1f} °C for the date", f"shortwave albedo {ALBEDO}, longwave emissivity 0.97", f"neutral bulk coefficients Ce = Ch = {CE:g}",
                            "wind speed from CCMP; radiation, air temperature, humidity and pressure from NASA POWER, whose last valid day can be several days older than the CCMP week"]}


# ---------------------------------------------------------------------------------------------------- ENSO
def parse_sstoi(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines()[1:]:
        p = line.split()
        if len(p) >= 10:
            try:
                rows.append({"year": int(p[0]), "month": int(p[1]), "nino34": float(p[8]), "nino34_anomaly": float(p[9])})
            except ValueError:
                continue
    return rows


def enso() -> dict:
    r = requests.get(CPC, timeout=oc.TIMEOUT, headers={"User-Agent": "OceanMind/1.0 (research dashboard)"})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    rows = parse_sstoi(r.text)
    if len(rows) < 12:
        raise RuntimeError("unexpected CPC file")
    last = rows[-1]
    out = {"available": True, "source": "NOAA Climate Prediction Center", "dataset": "Monthly Niño indices (OISST-based `sstoi.indices`) and Oceanic Niño Index", "unit": "°C", "temporal_resolution": "monthly",
           "kind": "contextual climate index", "latest_month": f"{last['year']}-{last['month']:02d}", "dataset_end": f"{last['year']}-{last['month']:02d}", "nino34_anomaly": last["nino34_anomaly"], "nino34": last["nino34"],
           "recent": [{"month": f"{x['year']}-{x['month']:02d}", "nino34_anomaly": x["nino34_anomaly"]} for x in rows[-6:]], "spatial_resolution": "Niño 3.4 box (5°S-5°N, 170°W-120°W)"}
    try:
        from app.services import climate_indices
        c = climate_indices.context(date(last["year"], last["month"], 15).isoformat())
        if c and c.get("oni"):
            out["oni"] = c["oni"]
    except Exception as exc:  # noqa: BLE001 - the ONI is optional here
        log.info("ONI unavailable: %s", exc)
    return out


# ---------------------------------------------------------------------------------------------------- assembling, cache, background fetch
def build(lat: float, lon: float, d: date | None = None) -> dict:
    d = d or date.today()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    jobs = {"winds": lambda: winds(lat, lon), "heat_flux": lambda: heat_flux_climatology(lat, lon, d), "radiation": lambda: power_met(lat, lon, d), "sea_level": lambda: sea_level(lat, lon), "currents": lambda: oc.currents(lat, lon), "enso": enso}
    out: dict = {"schema": SCHEMA, "fetched_at": now, "query": {"lat": lat, "lon": lon}, "sources": {}}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {k: ex.submit(fn) for k, fn in jobs.items()}
    for k, f in futs.items():
        try:
            out[k] = f.result()
            if k == "radiation" and out[k].get("available"):                                 # wind over the radiation days, so that wind, humidity and radiation describe the same week
                try:
                    out[k]["wind_window"] = wind_window(lat, lon, date.fromisoformat(out[k]["dataset_end"]))
                except Exception as exc:  # noqa: BLE001
                    out[k]["wind_window"] = None
                    log.info("wind over the radiation window unavailable: %s", exc)
            out[k]["retrieved"] = now[:10]
            out["sources"][k] = {"status": "ok" if out[k].get("available", True) else "no_data", "dataset_end": out[k].get("dataset_end"), "retrieved": now[:10], "message": out[k].get("message")}
        except Exception as exc:  # noqa: BLE001 - a failing source must not stop the others
            out[k] = {"available": False, "message": f"could not be retrieved: {exc}"}
            out["sources"][k] = {"status": "unavailable", "dataset_end": None, "retrieved": None, "message": str(exc)[:160]}
    if all(s["status"] == "unavailable" for s in out["sources"].values()):
        raise RuntimeError("no physical-driver source could be retrieved")
    return out


def cache_key(lat: float, lon: float, d: date) -> str:
    """The cache cell of a place and the first day of the heat-flux window (the forecast's first day), so a payload is never reused for another day."""
    return f"{_key(lat, lon)}_{d.isoformat()}"


def _background(key: str, lat: float, lon: float, d: date) -> None:
    try:
        _save(key, build(lat, lon, d))
        _failed.pop(key, None)
    except Exception as exc:  # noqa: BLE001
        _failed[key] = datetime.now(timezone.utc)
        log.warning("physical-driver fetch failed for %s: %s", key, exc)
    finally:
        with _mutex:
            _inflight.pop(key, None)


def location_drivers(lat: float, lon: float, wait_s: float = 6.0, d: date | None = None) -> dict | None:
    """The cached payload for the place with a `status` (cached | live | stale_cache | refreshing | unavailable), fetching in the background on a miss. None when switched off."""
    if not ENABLED:
        return None
    key = cache_key(lat, lon, d or date.today())
    cached = _load(key)
    now = datetime.now(timezone.utc)
    if cached and cached.get("schema") == SCHEMA:
        ttl = RETRY_AFTER if any(v.get("status") == "unavailable" for v in (cached.get("sources") or {}).values()) else TTL          # a source that failed is tried again soon, not kept for 12 hours
        if now - datetime.fromisoformat(cached["fetched_at"]) < ttl:
            return {**cached, "status": "cached"}
    else:
        cached = None
    failed = _failed.get(key)
    if failed and now - failed < RETRY_AFTER:
        return {**cached, "status": "stale_cache"} if cached else {"status": "unavailable", "sources": {}}
    with _mutex:
        th = _inflight.get(key)
        if th is None:
            th = threading.Thread(target=_background, args=(key, lat, lon, d or date.today()), daemon=True, name=f"phys-{key}")
            _inflight[key] = th
            th.start()
    th.join(wait_s)
    if th.is_alive():
        return {**cached, "status": "stale_cache"} if cached else {"status": "refreshing", "sources": {}}
    fresh = _load(key)
    if fresh and fresh.get("schema") == SCHEMA and datetime.now(timezone.utc) - datetime.fromisoformat(fresh["fetched_at"]) < TTL:
        return {**fresh, "status": "live"}                                                 # only a file written by the fetch that just finished is "live"
    return {**cached, "status": "stale_cache"} if cached else {"status": "unavailable", "sources": {}}


def clear_state() -> None:
    _inflight.clear()
    _failed.clear()
    _grid_cache.clear()
