"""A small, polite client for the OBIS API (https://api.obis.org/v3): geographic box queries, date filters, paging, retries, a request timeout and a minimum interval between
calls. It only reads from OBIS; it never downloads the database. Nothing here invents a value: a failed request raises ObisError and the caller decides what to fall back on."""
from __future__ import annotations

import logging
import math
import threading
import time
from datetime import date

import requests

from app.core.config import get_settings

log = logging.getLogger("ocean_platform")

TIMEOUT = (5, 20)                    # connect, read (seconds)
RETRIES = 3
MIN_INTERVAL_S = 0.25                # rate limit: at most ~4 requests per second from this process
PAGE = 1000
RECORD_FIELDS = "id,scientificName,species,aphiaID,class,decimalLatitude,decimalLongitude,eventDate,datasetName,category"

_lock = threading.Lock()
_last = [0.0]


class ObisError(RuntimeError):
    """OBIS could not be reached or answered with an error after the retries."""


def _wrap_lon(x: float) -> float:
    return ((x + 180.0) % 360.0) - 180.0


def geometry(lat: float, lon: float, half_deg: float) -> str:
    """WKT box of +-half_deg around the point. A box that crosses the antimeridian becomes a MULTIPOLYGON of two boxes, so -179 and +179 are neighbours."""
    la0, la1 = max(-90.0, lat - half_deg), min(90.0, lat + half_deg)
    c = _wrap_lon(lon)
    lo0, lo1 = c - half_deg, c + half_deg

    def box(a, b):
        return f"(({a:g} {la0:g},{b:g} {la0:g},{b:g} {la1:g},{a:g} {la1:g},{a:g} {la0:g}))"
    if half_deg >= 180:
        return f"POLYGON{box(-180, 180)}"
    if lo0 < -180:
        return f"MULTIPOLYGON({box(lo0 + 360, 180)},{box(-180, lo1)})"
    if lo1 > 180:
        return f"MULTIPOLYGON({box(lo0, 180)},{box(-180, lo1 - 360)})"
    return f"POLYGON{box(lo0, lo1)}"


def _get(path: str, params: dict) -> dict:
    url = get_settings().OBIS_API_BASE_URL.rstrip("/") + path
    last = "no attempt"
    for attempt in range(1, RETRIES + 1):
        with _lock:                                           # rate limit: spread the requests of every thread
            wait = MIN_INTERVAL_S - (time.monotonic() - _last[0])
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.monotonic()
        try:
            r = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "OceanMind/1.0 (research dashboard)"})
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
            elif r.status_code != 200:
                raise ObisError(f"OBIS answered HTTP {r.status_code} for {path}")
            else:
                return r.json()
        except requests.RequestException as exc:
            last = exc.__class__.__name__
        time.sleep(0.5 * attempt)                             # back off before the next attempt
    raise ObisError(f"OBIS unavailable ({last}) for {path} after {RETRIES} attempts")


def _since(start: date | None) -> dict:
    return {"startdate": start.isoformat()} if start else {}


def total(lat: float, lon: float, half_deg: float, start: date | None = None) -> int:
    """How many occurrence records fall in the box (and after `start`), without downloading them."""
    d = _get("/occurrence", {"geometry": geometry(lat, lon, half_deg), "size": 1, "fields": "id", **_since(start)})
    return int(d.get("total", 0))


def checklist(lat: float, lon: float, half_deg: float, start: date | None = None, redlist: bool = False, size: int = 1000) -> list[dict]:
    """Taxa recorded in the box with their record counts and, where OBIS has one, the IUCN Red List `category`."""
    p = {"geometry": geometry(lat, lon, half_deg), "size": size, **_since(start)}
    if redlist:
        p["redlist"] = "true"
    return _get("/checklist", p).get("results", [])


def occurrences(lat: float, lon: float, half_deg: float, start: date | None = None, redlist: bool = False, limit: int = 3000) -> list[dict]:
    """Up to `limit` records of the box, a page at a time (OBIS `after` cursor)."""
    out: list[dict] = []
    after = None
    while len(out) < limit:
        p = {"geometry": geometry(lat, lon, half_deg), "size": min(PAGE, limit - len(out)), "fields": RECORD_FIELDS, **_since(start)}
        if redlist:
            p["redlist"] = "true"
        if after:
            p["after"] = after
        page = _get("/occurrence", p).get("results", [])
        out += page
        if len(page) < p["size"]:
            break
        after = page[-1].get("id")
        if not after:
            break
    return out


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(((lon2 - lon1 + 180) % 360) - 180)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))
