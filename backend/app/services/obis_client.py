"""Thin, failure-tolerant clients for the public OBIS and WoRMS REST APIs (no keys needed).

Every function raises ExternalServiceError on network/HTTP problems so callers can show a clear "source unavailable"
state instead of a stack trace. Responses are cached in-process for a short time to avoid hammering the services.
"""
from __future__ import annotations

import time
from typing import Any

import requests

from app.core.config import get_settings

WORMS_BASE = "https://www.marinespecies.org/rest"
_TTL_SECONDS = 600
_cache: dict[tuple, tuple[float, Any]] = {}


class ExternalServiceError(Exception):
    pass


def _get(url: str, params: dict | None = None, timeout: float = 25.0) -> Any:
    key = (url, tuple(sorted((params or {}).items())))
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < _TTL_SECONDS:
        return hit[1]
    try:
        response = requests.get(url, params=params, timeout=timeout)
        if response.status_code == 204:
            data: Any = []
        else:
            response.raise_for_status()
            data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ExternalServiceError(f"{url} unavailable: {exc}") from exc
    _cache[key] = (time.monotonic(), data)
    return data


def _obis(path: str) -> str:
    return f"{get_settings().OBIS_API_BASE_URL}{path}"


def taxon_complete(query: str, limit: int = 10) -> list[dict]:
    """Species-rank accepted taxa matching a name fragment (OBIS taxon autocomplete)."""
    rows = _get(_obis(f"/taxon/complete/{query}"))
    out = []
    for r in rows:
        if r.get("rank") != "Species":
            continue
        accepted = r.get("acceptedNameUsageID")
        if accepted not in (None, str(r["id"]), r["id"]):
            continue  # synonym
        out.append(r)
        if len(out) >= limit:
            break
    return out


def taxon(aphia_id: int) -> dict | None:
    payload = _get(_obis(f"/taxon/{aphia_id}"))
    results = payload.get("results", []) if isinstance(payload, dict) else []
    return results[0] if results else None


def redlist_category(scientific_name: str) -> str | None:
    """IUCN Red List category (VU/EN/CR/EX) if OBIS lists the species as threatened, else None (status not confirmed)."""
    payload = _get(_obis("/checklist/redlist"), {"scientificname": scientific_name})
    for r in payload.get("results", []) if isinstance(payload, dict) else []:
        if r.get("scientificName") == scientific_name:
            return r.get("category")
    return None


def english_vernaculars(aphia_id: int) -> list[str]:
    try:
        rows = _get(f"{WORMS_BASE}/AphiaVernacularsByAphiaID/{aphia_id}")
    except ExternalServiceError:
        return []
    return [v["vernacular"] for v in rows if v.get("language_code") == "eng"]


def gbif_iucn(scientific_name: str) -> dict | None:
    """IUCN Red List category for a species as exposed by GBIF ({code, category, iucn_taxon_id}), or None if GBIF has no
    IUCN assessment for it / is unreachable. Codes: EX EW CR EN VU NT LC DD NE."""
    try:
        match = _get("https://api.gbif.org/v1/species/match", {"name": scientific_name})
        key = match.get("usageKey")
        if not key or match.get("matchType") not in ("EXACT",):
            return None
        row = _get(f"https://api.gbif.org/v1/species/{key}/iucnRedListCategory")
    except ExternalServiceError:
        return None
    code = row.get("code") if isinstance(row, dict) else None
    if not code:
        return None
    return {"code": code, "category": row.get("category"), "iucn_taxon_id": row.get("iucnTaxonID")}


def gbif_common_name(scientific_name: str) -> str | None:
    """Most frequent English vernacular name across GBIF's source datasets (a consensus pick; GBIF has no single
    authoritative common name). None if GBIF is unreachable or has no English name."""
    try:
        match = _get("https://api.gbif.org/v1/species/match", {"name": scientific_name})
        key = match.get("usageKey")
        if not key or match.get("matchType") not in ("EXACT", "HIGHERRANK"):
            return None
        rows = _get(f"https://api.gbif.org/v1/species/{key}/vernacularNames", {"limit": 300}).get("results", [])
    except ExternalServiceError:
        return None
    counts: dict[str, list] = {}
    for r in rows:
        if r.get("language") == "eng" and r.get("vernacularName"):
            name = r["vernacularName"].strip()
            counts.setdefault(name.lower(), []).append(name)
    if not counts:
        return None
    best = min(counts.values(), key=lambda v: (-len(v), len(v[0])))
    return best[0].capitalize()


def occurrence_grid(scientific_name: str, precision: int = 3, geometry: str | None = None) -> dict:
    params: dict = {"scientificname": scientific_name}
    if geometry:
        params["geometry"] = geometry
    return _get(_obis(f"/occurrence/grid/{precision}"), params, timeout=40.0)
