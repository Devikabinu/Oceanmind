"""Loads the ML pipeline's dashboard export once and exposes grid lookups with explicit coverage checks.

Files (processed/model/dashboard/): snapshot.npz + snapshot.json (required), heatwave_state.npz + heatwave.json and
point_history.npz (optional: features depending on them report "unavailable" instead of failing).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core.config import get_settings


class OutputsUnavailable(Exception):
    pass


def processed_dir() -> Path:
    configured = get_settings().PROCESSED_DIR
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "processed"


def dashboard_dir() -> Path:
    return processed_dir() / "model" / "dashboard"


@dataclass
class Env:
    info: dict
    z: dict
    hw: dict | None = None
    hwinfo: dict | None = None
    hist: dict | None = None
    res: float = 0.25
    bounds: dict = field(default_factory=dict)

    @property
    def lat(self):
        return self.z["lat"]

    @property
    def lon(self):
        return self.z["lon"]

    def cell(self, lat: float, lon: float) -> tuple[int, int] | None:
        """Nearest grid cell, or None when the point lies outside the study-region grid (no data there)."""
        b = self.bounds
        if not (b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]):
            return None
        i = int(np.abs(self.lat - lat).argmin())
        j = int(np.abs(self.lon - lon).argmin())
        return i, j

    def is_ocean(self, i: int, j: int) -> bool:
        return bool(self.z["ocean"][i, j])


def _npz(path: Path) -> dict:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


@lru_cache(maxsize=2)
def _load(key: tuple) -> Env:
    d = dashboard_dir()
    info = json.loads((d / "snapshot.json").read_text())
    z = _npz(d / "snapshot.npz")
    hw = _npz(d / "heatwave_state.npz") if (d / "heatwave_state.npz").exists() else None
    hwinfo = json.loads((d / "heatwave.json").read_text()) if (d / "heatwave.json").exists() else None
    hist = _npz(d / "point_history.npz") if (d / "point_history.npz").exists() else None
    res = float(info.get("grid", {}).get("resolution_deg", 0.25))
    lat, lon = z["lat"], z["lon"]
    bounds = {"lat_min": float(lat.min()) - res / 2, "lat_max": float(lat.max()) + res / 2,
              "lon_min": float(lon.min()) - res / 2, "lon_max": float(lon.max()) + res / 2}
    return Env(info=info, z=z, hw=hw, hwinfo=hwinfo, hist=hist, res=res, bounds=bounds)


def env() -> Env:
    d = dashboard_dir()
    snap = d / "snapshot.npz"
    if not snap.exists():
        raise OutputsUnavailable("dashboard snapshot not found; run `python -m oceanmind_model export-dashboard`")
    key = tuple((p.name, p.stat().st_mtime) for p in sorted(d.glob("*")) if p.is_file())
    return _load(key)


def clear_cache() -> None:
    _load.cache_clear()


def read_json(path: Path) -> dict:
    if not path.exists():
        raise OutputsUnavailable(f"{path.name} not found; run the ML pipeline step that creates it")
    return json.loads(path.read_text())
