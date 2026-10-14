"""Inference path: the most recent model input window, using NRT where FINAL is not yet available."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from . import features, normalize
from .align import latest_available_date, load_aligned, make_grid
from .clean import preclean
from .config import Cfg, load_config


def build_latest_window(date=None, config="config.yaml") -> dict:
    """Build the model input whose last input day is `date` (default: latest available date).

    Applies the saved land mask, clip limits, climatology and stats.json. Returns a dict with
      x            float32 (T, C, H, W) normalised input, channels = meta['forecast_channels']
      dates        the T input dates
      nrt_flags    per input day: True if any variable came from NRT (FINAL unavailable)
      n_nrt_days   sum(nrt_flags) -- how many of the T input days are NRT-derived
      ocean        (H, W) bool
      missing_frac per-day fraction of ocean cells without SST (after gap filling)
    """
    cfg = config if isinstance(config, Cfg) else load_config(config)
    out = Path(cfg.paths.out_dir)
    meta = json.loads((out / "meta.json").read_text())
    stats_doc = json.loads((out / "stats.json").read_text())
    names = stats_doc["channel_order"]
    ocean = ~np.load(out / "land_mask.npy")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        clim_ds = xr.open_zarr(out / "climatology.zarr").load()
    clim = {v: clim_ds[v].values for v in clim_ds.data_vars}

    T = meta["lookback_days"]
    date = latest_available_date(cfg) if date is None else pd.Timestamp(date).floor("D")
    t0 = date - pd.Timedelta(days=T - 1 + features.lookback_margin(cfg))
    lat, lon = make_grid(cfg)
    al = load_aligned(cfg, lat, lon, t0, date, include_nrt=True)
    ref = al.data[cfg.time.reference_var]
    if np.isnan(ref[-1][ocean]).all():
        raise ValueError(f"no {cfg.time.reference_var} data for {date.date()} in FINAL or NRT stores")

    limits = {v: tuple(l) for v, l in stats_doc["clip_limits"].items()}
    clean, _ = preclean(cfg, al.data, ocean, limits, [slice(0, len(al.times))])
    cube, got = features.assemble_features(cfg, clean, al.times, lat, clim)
    if got != names:
        raise ValueError("channel layout differs from the one used at build time; rebuild with the current config")
    normalize.zscore(cube, names, stats_doc["channels"])
    normalize.finish(cube, ocean)

    x = cube[-T:][:, [names.index(c) for c in meta["forecast_channels"]]]
    nrt = al.nrt[-T:]
    miss = 1.0 - cube[-T:, names.index(f"mask_{cfg.time.reference_var}")][:, ocean].mean(axis=1)
    assert np.isfinite(x).all()
    return {
        "x": x.astype("float32"),
        "dates": [str(d.date()) for d in al.times[-T:]],
        "channels": list(meta["forecast_channels"]),
        "nrt_flags": nrt.tolist(),
        "n_nrt_days": int(nrt.sum()),
        "n_final_days": int(T - nrt.sum()),
        "ocean": ocean,
        "missing_frac": miss,
        "as_of": str(date.date()),
    }
