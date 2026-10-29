"""Biodiversity of a clicked place from the OBIS API, never faster than the user can wait and never invented.

For a place the service searches boxes of growing size (local, nearby, regional, regional Pacific) and uses the smallest one that holds useful data: first among recent records
(last two years), and only when no box does, among older records, which are then labelled historical. The answer is cached on disk (the key is the rounded place, the window and the
schema version), so a click is served from the cache; a cache miss starts a background fetch and waits only a few seconds. When OBIS cannot be reached the previous cached answer
(marked stale) or, failing that, nothing: the caller then uses the stored OBIS records of the project. Every number here is a count of real OBIS records."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.services import obis_live as oc

log = logging.getLogger("ocean_platform")

ENABLED = True                         # switched off by the test configuration so that no test reaches the network
TIERS = [(0.5, "local"), (2.0, "nearby"), (5.0, "nearby"), (10.0, "regional"), (20.0, "regional"), (40.0, "regional Pacific")]
MIN_USEFUL = 25                        # records a box needs before it counts as useful
RECENT_DAYS = 730
TTL = timedelta(days=7)
RETRY_AFTER = timedelta(minutes=5)     # after a failed fetch do not ask OBIS again for this place for a while
SCHEMA = 2
THREATENED = {"CR", "EN", "VU"}
NAMES = {"local": "Local", "nearby": "Nearby", "regional": "Regional", "regional Pacific": "Regional Pacific"}

_inflight: dict[str, threading.Thread] = {}
_failed: dict[str, datetime] = {}
_mutex = threading.Lock()


def cache_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "cache" / "biodiversity"


def _key(lat: float, lon: float) -> str:
    la, lo = round(lat * 2) / 2, round(((lon + 180) % 360 - 180) * 2) / 2          # a 0.5 degree cache cell
    return f"v{SCHEMA}_{la:+.1f}_{lo:+.1f}_{RECENT_DAYS}d"


def _file(key: str) -> Path:
    return cache_dir() / f"obis_{hashlib.sha1(key.encode()).hexdigest()[:16]}.json"


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


def _day(s: str | None) -> str | None:
    return s[:10] if s else None


def build(lat: float, lon: float, today: date | None = None) -> dict:
    """Query OBIS (smallest useful box, recent first) and return the payload that is cached. Raises ObisError when OBIS cannot be reached."""
    today = today or date.today()
    start = today - timedelta(days=RECENT_DAYS)
    trail, chosen, historical = [], None, False
    for window, hist in ((start, False), (None, True)):                              # recent records first; older records only when no box has recent ones
        for half, scope in TIERS:
            n = oc.total(lat, lon, half, window)
            trail.append({"half_width_deg": half, "scope": scope, "records": n, "window": "older records included" if hist else "last 2 years"})
            if n >= MIN_USEFUL:
                chosen, historical = (half, scope), hist
                break
        if chosen:
            break
    base = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Ocean Biodiversity Information System (OBIS)", "api": "https://api.obis.org/v3",
            "query": {"lat": lat, "lon": lon, "recent_from": start.isoformat(), "recent_days": RECENT_DAYS}, "trail": trail, "schema": SCHEMA}
    if not chosen:
        return {**base, "available": False, "message": "OBIS holds fewer than 25 occurrence records within 40° of this location."}
    half, scope = chosen
    win = None if historical else start
    n_all = oc.total(lat, lon, half, None)
    chk = oc.checklist(lat, lon, half, win)
    red = {r["scientificName"]: r for r in oc.checklist(lat, lon, half, win, redlist=True)}
    recs = oc.occurrences(lat, lon, half, win, limit=2500)
    seen = {r.get("id") for r in recs}
    recs += [r for r in oc.occurrences(lat, lon, half, win, redlist=True, limit=2000) if r.get("id") not in seen]
    per: dict[str, dict] = {}
    for r in recs:
        nm = r.get("species") or r.get("scientificName")
        if not nm or r.get("decimalLatitude") is None:
            continue
        e = per.setdefault(nm, {"n": 0, "nearest": 1e9, "latest": None, "datasets": set()})
        e["n"] += 1
        e["nearest"] = min(e["nearest"], oc.distance_km(lat, lon, r["decimalLatitude"], r["decimalLongitude"]))
        d = _day(r.get("eventDate"))
        if d and (e["latest"] is None or d > e["latest"]):
            e["latest"] = d
        if r.get("datasetName"):
            e["datasets"].add(r["datasetName"])
    species = []
    for row in chk:
        if row.get("taxonRank") != "Species":
            continue
        nm = row["scientificName"]
        cat = row.get("category") or (red.get(nm) or {}).get("category")
        e = per.get(nm) or {}
        species.append({"scientific_name": nm, "aphia_id": row.get("taxonID"), "group": row.get("class") or row.get("phylum") or row.get("kingdom"), "category": cat,
                        "records": row.get("records", 0), "sampled_records": e.get("n", 0), "nearest_km": None if not e else round(e["nearest"]), "latest_record": e.get("latest"),
                        "datasets": sorted(e.get("datasets", []))[:3]})
    for nm, row in red.items():                                                      # a threatened taxon not listed as a species row (rank varies) is still kept
        if row.get("taxonRank") == "Species" and not any(s["scientific_name"] == nm for s in species):
            e = per.get(nm) or {}
            species.append({"scientific_name": nm, "aphia_id": row.get("taxonID"), "group": row.get("class") or row.get("phylum"), "category": row.get("category"), "records": row.get("records", 0),
                            "sampled_records": e.get("n", 0), "nearest_km": None if not e else round(e["nearest"]), "latest_record": e.get("latest"), "datasets": sorted(e.get("datasets", []))[:3]})
    species.sort(key=lambda s: (s["category"] not in THREATENED, -s["records"]))
    records = [[round(r["decimalLatitude"], 3), round(r["decimalLongitude"], 3), r.get("species") or r.get("scientificName"), _day(r.get("eventDate")), r.get("category")]
               for r in recs if r.get("decimalLatitude") is not None]
    return {**base, "available": True, "scope": scope, "half_width_deg": half, "historical": historical, "window_start": None if historical else start.isoformat(),
            "records_in_box": next(t["records"] for t in reversed(trail) if t["half_width_deg"] == half), "records_all_time": n_all, "sampled_records": len(records),
            "taxa": len(chk), "species": species, "records": records}


def _background(key: str, lat: float, lon: float) -> None:
    try:
        _save(key, build(lat, lon))
        _failed.pop(key, None)
    except Exception as exc:  # noqa: BLE001 - a failed refresh must never take the app down
        _failed[key] = datetime.now(timezone.utc)
        log.warning("OBIS fetch failed for %s: %s", key, exc)
    finally:
        with _mutex:
            _inflight.pop(key, None)


def location_biodiversity(lat: float, lon: float, wait_s: float = 5.0) -> dict | None:
    """The cached OBIS answer for the place, with `status`: cached | live | stale_cache | refreshing | unavailable. None when live OBIS is switched off."""
    if not ENABLED:
        return None
    key = _key(lat, lon)
    cached = _load(key)
    now = datetime.now(timezone.utc)
    if cached and cached.get("schema") == SCHEMA:
        age = now - datetime.fromisoformat(cached["fetched_at"])
        if age < TTL:
            return {**cached, "status": "cached"}
    else:
        cached = None
    failed = _failed.get(key)
    if failed and now - failed < RETRY_AFTER:
        return {**cached, "status": "stale_cache"} if cached else {"available": False, "status": "unavailable", "message": "OBIS could not be reached a moment ago; stored records are shown."}
    with _mutex:
        th = _inflight.get(key)
        if th is None:
            th = threading.Thread(target=_background, args=(key, lat, lon), daemon=True, name=f"obis-{key}")
            _inflight[key] = th
            th.start()
    th.join(wait_s)
    if th.is_alive():
        return {**cached, "status": "stale_cache"} if cached else {"available": False, "status": "refreshing", "message": "Fetching the latest OBIS records for this area."}
    fresh = _load(key)
    if fresh and fresh.get("schema") == SCHEMA and (now - datetime.fromisoformat(fresh["fetched_at"])) < TTL:
        return {**fresh, "status": "live"}
    return {**cached, "status": "stale_cache"} if cached else {"available": False, "status": "unavailable", "message": "OBIS could not be reached; stored records are shown."}


def clear_state() -> None:
    _inflight.clear()
    _failed.clear()
