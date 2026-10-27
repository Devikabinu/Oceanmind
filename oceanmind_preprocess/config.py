"""Config loading: a dict with attribute access. No defaults live in code; config.yaml is the source."""
from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ["paths", "grid", "time", "raw", "missing", "outliers", "climatology", "features",
            "splits", "normalization", "forecast", "anomaly", "biodiversity", "report"]
RAW_SOURCES = ("stores", "provider")


class Cfg(dict):
    def __init__(self, d=None):
        super().__init__()
        for k, v in (d or {}).items():
            self[k] = Cfg(v) if isinstance(v, dict) else v

    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k) from None

    def __setattr__(self, k, v):
        self[k] = v


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read_yaml(path: Path) -> dict:
    """Read a YAML config; an `extends: other.yaml` key (relative to this file) is deep-merged underneath it."""
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)
    parent = d.pop("extends", None)
    return _merge(_read_yaml((path.parent / parent).resolve()), d) if parent else d


def apply_provider_domain(cfg, provider=None) -> Cfg:
    """For raw.source == 'provider': the processing grid IS the provider's grid. Sets grid.lat_min/lat_max/lon_min/lon_max (cell centres) and
    grid.resolution from the provider so that no domain coordinates are repeated in the preprocessing config. Longitudes follow the provider's continuous
    east-positive axis (e.g. 100.5..289.5 for the Pacific), see align.normalize_longitude."""
    if provider is None:
        from oceanmind_environment import build_provider  # lazy import: only provider-based configs need it
        provider = build_provider(cfg)
    lat, lon = provider.grid()
    cfg.grid.update(lat_min=float(lat[0]), lat_max=float(lat[-1]), lon_min=float(lon[0]), lon_max=float(lon[-1]),
                    resolution=float(provider.metadata().resolution_deg))
    return cfg


def load_config(path) -> Cfg:
    path = Path(path).resolve()
    cfg = Cfg(_read_yaml(path))
    missing = [k for k in REQUIRED if k not in cfg]
    if missing:
        raise KeyError(f"config {path} is missing sections: {missing}")
    base = path.parent
    for key in ("raw_dir", "out_dir"):
        p = Path(cfg.paths[key])
        cfg.paths[key] = str(p if p.is_absolute() else (base / p).resolve())
    cfg["config_path"] = str(path)
    if cfg.anomaly.days not in (1, 3):
        raise ValueError("anomaly.days must be 1 or 3")
    source = cfg.raw.get("source", "stores")
    if source not in RAW_SOURCES:
        raise ValueError(f"raw.source must be one of {RAW_SOURCES}, got {source!r}")
    if source == "provider":
        apply_provider_domain(cfg)
    return cfg
