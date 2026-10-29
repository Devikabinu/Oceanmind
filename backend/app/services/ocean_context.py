"""Ecological and physical CONTEXT for a place from NOAA ERDDAP: chlorophyll-a (NOAA VIIRS ocean colour) and geostrophic surface currents (NOAA altimetry). These values are shown next
to the forecast as context. They are not inputs of the ConvLSTM, they are not part of the risk score, and nothing here says that they explain the SST or the forecast.

Only datasets with a clear meaning, Pacific coverage and a stated time range are used:
  chlorophyll-a: noaa_snpp_chla_daily (daily, 2012-present, 0.0375 deg) for the recent weeks and noaa_snpp_chla_monthly for the same calendar month of earlier years;
  currents: noaacwBLENDEDNRTcurrentsDaily (daily, 2015-present, 0.25 deg), geostrophic velocity from altimetry (no wind-driven part).
Each value carries its source, dataset, observation date and resolution. A failed request leaves the cached answer (marked stale) or nothing; no value is ever filled in."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import math
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

log = logging.getLogger("ocean_platform")

ENABLED = True                           # switched off by the test configuration
TIMEOUT = (5, 30)
TTL = timedelta(hours=12)
RETRY_AFTER = timedelta(minutes=10)
SCHEMA = 1
PIFSC = "https://oceanwatch.pifsc.noaa.gov/erddap/griddap"
COASTWATCH = "https://coastwatch.noaa.gov/erddap/griddap"
CHL_DAILY, CHL_MONTHLY, CURRENTS = "noaa_snpp_chla_daily", "noaa_snpp_chla_monthly", "noaacwBLENDEDNRTcurrentsDaily"
MIN_PIXELS = 3                           # a day needs at least this many valid pixels in the window to count

_inflight: dict[str, threading.Thread] = {}
_failed: dict[str, datetime] = {}
_mutex = threading.Lock()


def cache_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "cache" / "ocean_context"


def _key(lat: float, lon: float) -> str:
    return f"v{SCHEMA}_{round(lat * 4) / 4:+.2f}_{round(((lon + 180) % 360 - 180) * 4) / 4:+.2f}"


def _file(key: str) -> Path:
    return cache_dir() / f"ctx_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


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


def _csv(url: str) -> list[dict]:
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "OceanMind/1.0 (research dashboard)"})
            if r.status_code == 200:
                rows = list(csv.DictReader(io.StringIO(r.text)))
                return rows[1:] if rows else []                      # the second line of an ERDDAP csv holds the units
            last = f"HTTP {r.status_code}"
            if r.status_code in (400, 404):
                break
        except requests.RequestException as exc:
            last = exc.__class__.__name__
    raise RuntimeError(f"ERDDAP request failed ({last})")


def _num(x: str) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return float("nan")
    return v


def _last_time(base: str, ds: str) -> date:
    rows = _csv(f"{base}/{ds}.csv?time%5B(last)%5D")
    return date.fromisoformat(rows[0]["time"][:10])


def _window(v: float, half: float, lo: float | None = None, hi: float | None = None) -> tuple[float, float]:
    return v - half, v + half


# ---------------------------------------------------------------------------------------------------- chlorophyll-a
def chlorophyll(lat: float, lon: float, today: date | None = None) -> dict:
    """Latest valid chlorophyll-a, the mean of the last 30 days, the change over them, and where the recent mean sits among the same calendar month of earlier years."""
    l360 = lon % 360
    a0, a1 = _window(lat, 0.25)
    o0, o1 = _window(l360, 0.25)
    end = _last_time(PIFSC, CHL_DAILY)
    start = end - timedelta(days=29)
    rows = _csv(f"{PIFSC}/{CHL_DAILY}.csv?chlor_a%5B({start.isoformat()}):1:({end.isoformat()})%5D%5B(0.0):1:(0.0)%5D%5B({a0:.4f}):4:({a1:.4f})%5D%5B({o0:.4f}):4:({o1:.4f})%5D")
    by_day: dict[str, list[float]] = {}
    for r in rows:
        v = _num(r["chlor_a"])
        if np.isfinite(v) and v > 0:
            by_day.setdefault(r["time"][:10], []).append(v)
    series = [(d, float(np.mean(v))) for d, v in sorted(by_day.items()) if len(v) >= MIN_PIXELS]
    base = {"source": "NOAA CoastWatch / STAR (served by NOAA PIFSC ERDDAP)", "dataset": f"{CHL_DAILY} (NOAA S-NPP VIIRS chlorophyll-a, daily)", "variable": "chlor_a", "unit": "mg m^-3",
            "spatial_resolution": "0.0375° (about 4 km); mean of the pixels within ±0.25° of the place", "temporal_resolution": "daily (cloud-free pixels only)", "dataset_end": end.isoformat()}
    if len(series) < 2:
        return {**base, "available": False, "message": f"No cloud-free chlorophyll-a pixels within ±0.25° of this place in the 30 days to {end.isoformat()} (cloud cover, sun glint or land)."}
    vals = [v for _, v in series]
    half = len(vals) // 2
    change = None if half < 2 else float(np.median(vals[half:]) - np.median(vals[:half]))
    out = {**base, "available": True, "latest": {"value": round(vals[-1], 4), "date": series[-1][0]}, "recent_mean": round(float(np.mean(vals)), 4), "valid_days": len(vals),
           "window": {"start": start.isoformat(), "end": end.isoformat()}, "change": None if change is None else round(change, 4),
           "change_pct": None if change is None or np.median(vals[:half]) <= 0 else round(100.0 * change / float(np.median(vals[:half])), 1)}
    try:
        mend = _last_time(PIFSC, CHL_MONTHLY)
        mrows = _csv(f"{PIFSC}/{CHL_MONTHLY}.csv?chlor_a%5B(2012-01-01):1:({mend.isoformat()})%5D%5B({a0:.4f}):4:({a1:.4f})%5D%5B({o0:.4f}):4:({o1:.4f})%5D")
        month = date.fromisoformat(series[-1][0]).month
        per: dict[str, list[float]] = {}
        for r in mrows:
            v = _num(r["chlor_a"])
            if np.isfinite(v) and v > 0 and int(r["time"][5:7]) == month:
                per.setdefault(r["time"][:7], []).append(v)
        hist = [float(np.mean(v)) for k, v in sorted(per.items()) if len(v) >= MIN_PIXELS and k[:4] != series[-1][0][:4]]
        if len(hist) >= 6:
            pct = 100.0 * float(np.mean([h < out["recent_mean"] for h in hist]))
            out["history"] = {"month": month, "years": len(hist), "median": round(float(np.median(hist)), 4), "percentile": round(pct, 1), "dataset": f"{CHL_MONTHLY} (monthly means, 2012-{mend.year})"}
    except Exception as exc:  # noqa: BLE001 - the historical comparison is optional
        log.info("chlorophyll history unavailable: %s", exc)
    out["text"] = _chl_text(out)
    return out


def _chl_text(c: dict) -> str:
    lv, rm = c["latest"], c["recent_mean"]
    few = " Only a few cloud-free days are available, so this is low confidence." if c["valid_days"] < 5 else ""
    parts = [f"Latest valid chlorophyll-a is {lv['value']:.3f} mg m⁻³ ({lv['date']}); the 30-day mean is {rm:.3f} mg m⁻³ from {c['valid_days']} cloud-free days.{few}"]
    h = c.get("history")
    if h:
        side = "elevated" if h["percentile"] >= 75 else "lower" if h["percentile"] <= 25 else "within the usual range"
        parts.append(f"Chlorophyll-a is {side} relative to the same month in {h['years']} earlier years (median {h['median']:.3f} mg m⁻³; the recent mean is {'lower than every one of them' if h['percentile'] <= 0 else 'higher than every one of them' if h['percentile'] >= 100 else f"higher than {h['percentile']:.0f}% of them"}).")
    if c.get("change") is not None and abs(c["change"]) > 0:
        pct = c.get("change_pct")
        if pct is not None and abs(pct) >= 10:
            parts.append(f"It has {'increased' if c['change'] > 0 else 'declined'} by {abs(pct):.0f}% over the last 30 days (second half versus first half).")
        else:
            parts.append("It has changed little over the last 30 days.")
    parts.append("This is ecological context: ocean-colour chlorophyll-a is an indicator of surface phytoplankton, not a measurement of ecosystem productivity or of any impact.")
    return " ".join(parts)


# ---------------------------------------------------------------------------------------------------- surface currents
def _bearing(u: float, v: float) -> float:
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def _compass(deg: float) -> str:
    return ["north", "north-east", "east", "south-east", "south", "south-west", "west", "north-west"][int(((deg + 22.5) % 360) // 45)]


def currents(lat: float, lon: float) -> dict:
    lon180 = ((lon + 180) % 360) - 180
    end = _last_time(COASTWATCH, CURRENTS)
    start = end - timedelta(days=7)
    a0, a1 = _window(lat, 0.125)
    o0, o1 = _window(lon180, 0.125)
    rng = f"[({start.isoformat()}):1:({end.isoformat()})][({a0:.4f}):1:({a1:.4f})][({o0:.4f}):1:({o1:.4f})]"
    rows = _csv(f"{COASTWATCH}/{CURRENTS}.csv?u_current{rng},v_current{rng}")
    days: dict[str, list[tuple[float, float]]] = {}
    for r in rows:
        u, v = _num(r["u_current"]), _num(r["v_current"])
        if np.isfinite(u) and np.isfinite(v):
            days.setdefault(r["time"][:10], []).append((u, v))
    series = []
    for d, uv in sorted(days.items()):
        u, v = float(np.mean([x[0] for x in uv])), float(np.mean([x[1] for x in uv]))
        series.append({"date": d, "u": round(u, 3), "v": round(v, 3), "speed": round(math.hypot(u, v), 3), "direction_deg": round(_bearing(u, v))})
    base = {"source": "NOAA CoastWatch (NESDIS/STAR)", "dataset": f"{CURRENTS} (geostrophic currents from altimetry, near-real-time)", "unit": "m/s", "spatial_resolution": "0.25°",
            "temporal_resolution": "daily", "dataset_end": end.isoformat()}
    if not series:
        return {**base, "available": False, "message": f"No altimetry-derived current at this place in the 8 days to {end.isoformat()} (land, coast or no coverage)."}
    cur = series[-1]
    earlier = series[:-1]
    d_speed = None if not earlier else round(cur["speed"] - float(np.mean([s["speed"] for s in earlier])), 3)
    d_dir = None if not earlier else round(((cur["direction_deg"] - earlier[0]["direction_deg"] + 180) % 360) - 180)
    near_equator = abs(lat) < 3.0
    text = (f"The geostrophic surface current is {cur['speed']:.2f} m/s toward the {_compass(cur['direction_deg'])} ({cur['direction_deg']}°) on {cur['date']}"
            + (f"; its speed is {abs(d_speed):.2f} m/s {'higher' if d_speed > 0 else 'lower'} than the mean of the previous {len(earlier)} days" + (f" and its direction has turned {abs(d_dir)}°" if d_dir is not None and abs(d_dir) >= 20 else "") if d_speed is not None else "")
            + ". Surface-current conditions provide additional physical context for the observed SST pattern; they are not an explanation of it and are not an input of the forecast model.")
    return {**base, "available": True, "latest": cur, "series": series, "speed_change": d_speed, "direction_change_deg": d_dir, "text": text,
            "caveat": "Geostrophic currents come from sea-surface height and omit the wind-driven part" + ("; the geostrophic approximation is unreliable within about 3° of the equator." if near_equator else ".")}


# ---------------------------------------------------------------------------------------------------- cache + background
def build(lat: float, lon: float) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out = {"schema": SCHEMA, "fetched_at": now, "chlorophyll": None, "currents": None, "errors": []}
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = {"chlorophyll": ex.submit(chlorophyll, lat, lon), "currents": ex.submit(currents, lat, lon)}
    for name, f in futs.items():
        try:
            out[name] = f.result()
            out[name]["retrieved"] = now[:10]
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{name}: {exc}")
    if out["chlorophyll"] is None and out["currents"] is None:
        raise RuntimeError("; ".join(out["errors"]) or "no data")
    return out


def _background(key: str, lat: float, lon: float) -> None:
    try:
        _save(key, build(lat, lon))
        _failed.pop(key, None)
    except Exception as exc:  # noqa: BLE001
        _failed[key] = datetime.now(timezone.utc)
        log.warning("ocean context fetch failed for %s: %s", key, exc)
    finally:
        with _mutex:
            _inflight.pop(key, None)


def location_context(lat: float, lon: float, wait_s: float = 5.0) -> dict | None:
    """{chlorophyll, currents, status} for the place from the cache, fetching in the background on a miss. None when switched off or nothing is available."""
    if not ENABLED:
        return None
    key = _key(lat, lon)
    cached = _load(key)
    now = datetime.now(timezone.utc)
    if cached and cached.get("schema") == SCHEMA:
        if now - datetime.fromisoformat(cached["fetched_at"]) < TTL:
            return {**cached, "status": "cached"}
    else:
        cached = None
    failed = _failed.get(key)
    if failed and now - failed < RETRY_AFTER:
        return {**cached, "status": "stale_cache"} if cached else None
    with _mutex:
        th = _inflight.get(key)
        if th is None:
            th = threading.Thread(target=_background, args=(key, lat, lon), daemon=True, name=f"ctx-{key}")
            _inflight[key] = th
            th.start()
    th.join(wait_s)
    if th.is_alive():
        return {**cached, "status": "stale_cache"} if cached else {"status": "refreshing", "chlorophyll": None, "currents": None}
    fresh = _load(key)
    if fresh and fresh.get("schema") == SCHEMA and datetime.now(timezone.utc) - datetime.fromisoformat(fresh["fetched_at"]) < TTL:
        return {**fresh, "status": "live"}
    return {**cached, "status": "stale_cache"} if cached else None


def clear_state() -> None:
    _inflight.clear()
    _failed.clear()
