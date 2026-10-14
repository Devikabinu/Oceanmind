"""Config loading: a dict with attribute access. No defaults live in code; config.yaml is the source."""
from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ["paths", "grid", "time", "raw", "missing", "outliers", "climatology", "features",
            "splits", "normalization", "forecast", "anomaly", "biodiversity", "report"]


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


def load_config(path) -> Cfg:
    path = Path(path).resolve()
    with open(path, encoding="utf-8") as f:
        cfg = Cfg(yaml.safe_load(f))
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
    return cfg
