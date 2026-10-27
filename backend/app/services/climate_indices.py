"""Large-scale climate context from published indices, used only as labelled context for anomaly explanations.

  * Oceanic Niño Index (ONI): NOAA Climate Prediction Center, https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt  (3-month running mean of Niño-3.4 SST anomalies)
  * Pacific Decadal Oscillation (PDO): NOAA NCEI ERSSTv5, https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat

The indices are downloaded by a job (`python -m app.jobs sync-climate-indices`, also part of scripts/refresh_pacific.py) and stored in data/climate_indices/indices.json; an API
request only reads that file. When the file is missing nothing is claimed about El Niño, La Niña or the PDO: the explanation says the index data are not loaded."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import requests

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
PDO_URL = "https://www.ncei.noaa.gov/pub/data/cmb/ersst/v5/index/ersst.v5.pdo.dat"
ONI_THRESHOLD = 0.5            # NOAA CPC: ONI at or beyond +/-0.5 degC marks El Nino / La Nina conditions (an episode needs 5 consecutive overlapping seasons)
SEASON_CENTRE = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6, "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}
MAX_STALE_MONTHS = 3           # an index value older than this relative to the requested date is not used


def index_file() -> Path:
    return Path(__file__).resolve().parents[3] / "data" / "climate_indices" / "indices.json"


def parse_oni(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0] in SEASON_CENTRE:
            try:
                year, anom = int(parts[1]), float(parts[3])
            except ValueError:
                continue
            if abs(anom) < 90:
                out[f"{year}-{SEASON_CENTRE[parts[0]]:02d}"] = {"value": anom, "season": f"{parts[0]} {year}"}
    return out


def parse_pdo(text: str) -> dict[str, dict]:
    out = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 13 and parts[0].isdigit():
            for m, v in enumerate(parts[1:], 1):
                try:
                    x = float(v)
                except ValueError:
                    continue
                if abs(x) < 90:                      # 99.99 marks a month not yet available
                    out[f"{parts[0]}-{m:02d}"] = {"value": x}
    return out


def sync() -> dict:
    """Download both indices, validate them and write the store. Raises on a failed or empty download so a bad file never replaces a good one."""
    data = {}
    for key, url, parse in (("oni", ONI_URL, parse_oni), ("pdo", PDO_URL, parse_pdo)):
        r = requests.get(url, timeout=60, headers={"User-Agent": "oceanmind-environment/1.0"})
        r.raise_for_status()
        series = parse(r.text)
        if len(series) < 100:
            raise ValueError(f"{key.upper()} download from {url} parsed to only {len(series)} values; keeping the previous file")
        data[key] = {"source": url, "series": series, "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "latest_month": max(series)}
    f = index_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(f)
    _load_cached.cache_clear()
    return {k: {"latest_month": v["latest_month"], "values": len(v["series"])} for k, v in data.items()}


@lru_cache(maxsize=1)
def _load_cached(path: str, stamp: float) -> dict:
    return json.loads(Path(path).read_text())


def _load():
    f = index_file()
    if not f.exists():
        return None
    return _load_cached(str(f), f.stat().st_mtime)


def _months_between(a: str, b: str) -> int:
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _latest_before(series: dict, month: str):
    keys = [k for k in series if k <= month]
    if not keys:
        return None
    k = max(keys)
    return k if _months_between(k, month) <= MAX_STALE_MONTHS else None


def context(date: str) -> dict | None:
    """ONI and PDO for the month of `date` (or the latest value up to three months earlier), with NOAA's own classification; None when the indices are not loaded."""
    d = _load()
    if d is None:
        return None
    month = date[:7]
    out: dict = {"retrieved_at": d["oni"]["retrieved_at"]}
    k = _latest_before(d["oni"]["series"], month)
    if k:
        v = d["oni"]["series"][k]
        state = "El Niño conditions" if v["value"] >= ONI_THRESHOLD else "La Niña conditions" if v["value"] <= -ONI_THRESHOLD else "neutral"
        out["oni"] = {"value": v["value"], "season": v["season"], "month": k, "state": state, "source": ONI_URL, "threshold": ONI_THRESHOLD}
    k = _latest_before(d["pdo"]["series"], month)
    if k:
        v = d["pdo"]["series"][k]
        out["pdo"] = {"value": v["value"], "month": k, "phase": "positive" if v["value"] > 0 else "negative", "source": PDO_URL}
    return out if ("oni" in out or "pdo" in out) else None
