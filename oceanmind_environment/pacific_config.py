"""The single place that defines the Pacific environmental domain. Values live in config.yaml (`environment_provider:`); nothing else in the code base should
repeat Pacific coordinates. Longitudes are east longitude 0..360 so the domain is contiguous across the antimeridian."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class PacificDomainConfig:
    provider: str
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    resolution_deg: float
    temporal_resolution: str      # pandas offset alias; the project is daily ("1D")
    start_date: str
    end_date: str                 # latest available timestamp of the generated record (fixed by configuration, not "today")
    seed: int
    mask_source: str
    store: str = ""                # processed observational store (observational providers only)

    def __post_init__(self):
        if not (-90 <= self.lat_min < self.lat_max <= 90):
            raise ValueError("latitude bounds must satisfy -90 <= lat_min < lat_max <= 90")
        if not (0 <= self.lon_min < self.lon_max <= 360):
            raise ValueError("longitude bounds must satisfy 0 <= lon_min < lon_max <= 360 (east longitude)")
        if self.resolution_deg <= 0 or self.resolution_deg > 10:
            raise ValueError("resolution_deg must be in (0, 10]")
        for span, name in ((self.lat_max - self.lat_min, "latitude"), (self.lon_max - self.lon_min, "longitude")):
            n = span / self.resolution_deg
            if abs(n - round(n)) > 1e-6:
                raise ValueError(f"the {name} span ({span} degrees) must be a whole multiple of resolution_deg ({self.resolution_deg}); "
                                 "otherwise the grid would not cover the stated extent")
        if self.temporal_resolution != "1D":
            raise ValueError("only a daily temporal resolution ('1D') is supported")
        if pd.Timestamp(self.start_date) > pd.Timestamp(self.end_date):
            raise ValueError("start_date must not be after end_date")

    @classmethod
    def from_cfg(cls, cfg) -> "PacificDomainConfig":
        """Build from a loaded project config (oceanmind_preprocess.config.load_config)."""
        e = cfg["environment_provider"]
        d, t = e["domain"], e["time"]
        return cls(provider=e["provider"], lat_min=float(d["lat_min"]), lat_max=float(d["lat_max"]), lon_min=float(d["lon_min"]),
                   lon_max=float(d["lon_max"]), resolution_deg=float(e["resolution_deg"]), temporal_resolution=str(e["temporal_resolution"]),
                   start_date=str(t["start"]), end_date=str(t.get("end") or t["start"]), seed=int(e.get("seed", 0)), mask_source=str(e.get("mask", {}).get("source", "dataset land-sea mask")),
                   store=str(cls._store_path(cfg)))

    @staticmethod
    def _store_path(cfg) -> str:
        from pathlib import Path
        s = cfg["environment_provider"].get("source", {}).get("store", "data/pacific_oisst/sst.zarr")
        p = Path(s)
        return str(p if p.is_absolute() else (Path(cfg["config_path"]).parent / p).resolve())
