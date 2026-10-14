"""The `build` orchestration: raw stores -> model-ready, leakage-safe datasets.

Memory model: raw/cleaned variables are held in RAM as (T,H,W) arrays; the feature cube is never materialised in
full. Each channel is computed once and streamed into per-split memory-mapped .npy files, and statistics /
normalisation / checks run in time chunks.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from . import biodiversity, features, normalize, validate, windows
from .align import land_mask_from, load_aligned, make_grid
from .clean import preclean
from .missing import compute_limits
from .splits import print_sizes, resolve_splits

log = logging.getLogger("oceanmind_preprocess")


def _channels(cfg, names, spec, kind):
    chans = names if spec == "all" else list(spec)
    bad = [c for c in chans if c not in names]
    if bad:
        raise KeyError(f"{kind}.channels {bad} not produced by the feature config; available: {names}")
    return chans


def build(cfg) -> dict:
    out = Path(cfg.paths.out_dir)
    for sub in ("cubes", "forecast", "anomaly", "biodiversity", "figures"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    # 1. alignment ---------------------------------------------------------------------------
    lat, lon = make_grid(cfg)
    al = load_aligned(cfg, lat, lon, cfg.time.start, cfg.time.end, include_nrt=cfg.raw.use_nrt_in_build)
    times = al.times
    log.info("aligned %d variables on %dx%d grid, %s .. %s (%d days)", len(al.data), len(lat), len(lon),
             times[0].date(), times[-1].date(), len(times))
    splits = resolve_splits(cfg, times)
    print_sizes(splits)
    train = splits["train"]

    land = land_mask_from(al.data[cfg.time.reference_var])
    ocean = ~land
    if not ocean.any():
        raise ValueError("land mask has no ocean cells -- check grid bounds and the reference variable")
    np.save(out / "land_mask.npy", land)

    # 2. missing data / outliers (limits from TRAIN only) -----------------------------------
    p = cfg.outliers
    limits = {v: compute_limits(a[train.sl], ocean, p.percentiles, p.max_samples, p.seed) for v, a in al.data.items()}
    segments = [sp.sl for sp in splits.values() if sp.n]
    clean, fill_report = preclean(cfg, al.data, ocean, limits, segments)
    for v, r in fill_report.items():
        print(f"  {v:<4} missing {r['pct_missing_before']:5.1f}% of ocean cell-days; "
              f"gap-filled {r['pct_of_missing_filled']:5.1f}% of those; still missing {r['pct_missing_after']:5.1f}%")

    # 3. features (TRAIN-only climatology), streamed into per-split memmaps ------------------
    clim, clim_raw = {}, {}
    for v in cfg.climatology.variables:
        clim_raw[v], clim[v] = features.daily_climatology(clean[v][train.sl], times[train.sl], cfg.climatology.smooth_sigma_days)
    xr.Dataset({v: (("dayofyear", "lat", "lon"), c) for v, c in clim.items()},
               coords={"dayofyear": np.arange(1, 367), "lat": lat, "lon": lon}).to_zarr(out / "climatology.zarr", mode="w")

    names = features.feature_names(cfg, clean.keys())
    H, W = land.shape
    cubes = {n: np.lib.format.open_memmap(out / "cubes" / f"{n}.npy", mode="w+", dtype="float32",
                                          shape=(sp.n, len(names), H, W))
             for n, sp in splits.items() if sp.n}
    for i, (nm, arr) in enumerate(features.iter_features(cfg, clean, times, lat, clim)):
        assert nm == names[i], (nm, names[i])
        for sname, cube in cubes.items():
            cube[:, i] = arr[splits[sname].sl]
        del arr

    # 4. normalisation (TRAIN only) ----------------------------------------------------------
    tr = cubes["train"]
    stats = normalize.fit_stats(tr, names, slice(0, train.n), ocean, cfg.normalization.min_std)
    for cube in cubes.values():
        normalize.zscore(cube, names, stats)
    moms = normalize.moments(tr, names, slice(0, train.n), ocean)
    for cube in cubes.values():
        normalize.finish(cube, ocean)
        cube.flush()
    validate.check_splits(splits)
    validate.check_train_norm(moms, stats, cfg.normalization.check_tol)
    (out / "stats.json").write_text(json.dumps({
        "train_period": [str(train.start.date()), str(train.end.date())],
        "channel_order": names,
        "channels": stats,
        "clip_limits": {v: list(l) for v, l in limits.items()},
    }, indent=2))

    # 5. indices ------------------------------------------------------------------------------
    fc, ac = cfg.forecast, cfg.anomaly
    fch = _channels(cfg, names, fc.channels, "forecast")
    ach = _channels(cfg, names, ac.channels, "anomaly")
    summary = {"splits": {}, "fill": fill_report, "moments": moms}
    dates_all = times.to_numpy()
    for name, sp in splits.items():
        if not sp.n:
            continue
        sub = cubes[name]
        validate.check_no_nan(name, sub, ocean)
        np.save(out / "cubes" / f"{name}_dates.npy", dates_all[sp.sl])
        np.save(out / "cubes" / f"{name}_nrt.npy", al.nrt[sp.sl])
        dts, nrt = times[sp.sl], al.nrt[sp.sl]
        fi, f_skip = windows.forecast_index(windows.daily_missing_frac(sub, names, ocean, fc.filter_vars), nrt, dts,
                                            fc.lookback_days, fc.horizons, fc.max_nan_frac, fc.stride)
        ai, a_skip = windows.anomaly_index(windows.daily_missing_frac(sub, names, ocean, ac.filter_vars), nrt, dts,
                                           ac.days, ac.max_nan_frac)
        validate.check_windows(fi, sp, fc.lookback_days, fc.horizons, sp.n)
        fi.to_parquet(out / "forecast" / f"windows_{name}.parquet")
        ai.to_parquet(out / "anomaly" / f"index_{name}.parquet")
        summary["splits"][name] = {"days": sp.n, "start": str(sp.start.date()), "end": str(sp.end.date()),
                                   "forecast_windows": len(fi), "forecast_skipped": f_skip,
                                   "anomaly_days": len(ai), "anomaly_skipped": a_skip}
        print(f"  {name:<5} forecast windows kept {len(fi):>5} (skipped {f_skip}); anomaly days kept {len(ai):>5} (skipped {a_skip})")

    (out / "meta.json").write_text(json.dumps({
        "lat": lat.tolist(), "lon": lon.tolist(), "resolution": cfg.grid.resolution,
        "channels": names,
        "lookback_days": fc.lookback_days, "horizons": list(fc.horizons),
        "target_channel": fc.target_channel, "forecast_channels": fch,
        "anomaly": {"days": ac.days, "channels": ach, "patch_size": ac.patch_size, "stride": ac.stride,
                    "min_ocean_frac": ac.min_ocean_frac},
        "splits": {k: v for k, v in summary["splits"].items()},
        "max_gap_days": cfg.missing.max_gap_days,
    }, indent=2))
    (out / "missing_report.json").write_text(json.dumps(fill_report, indent=2))

    # 6. biodiversity ------------------------------------------------------------------------
    obis = Path(cfg.paths.raw_dir) / cfg.paths.obis
    if cfg.biodiversity.enabled and obis.exists():
        tab = biodiversity.grid_obis(pd.read_parquet(obis), cfg, lat, lon, ocean)
        tab.to_parquet(out / "biodiversity" / "obis_monthly.parquet")
        if len(tab):
            biodiversity.to_dataset(tab, lat, lon).to_zarr(out / "biodiversity" / "obis_monthly.zarr", mode="w")
        summary["biodiversity"] = {"cell_months": len(tab), "records": int(tab.n_records.sum()) if len(tab) else 0}
        print(f"  biodiversity: {summary['biodiversity']['records']} records in {len(tab)} cell-months")
    else:
        log.warning("OBIS file not found or disabled (%s); skipping biodiversity", obis)

    # 7. report ------------------------------------------------------------------------------
    if cfg.report.enabled:
        from .report import write_report
        write_report(cfg, out, times, splits, land, al.data[cfg.time.reference_var], clean[cfg.time.reference_var],
                     cubes, names, stats, clim_raw, clim, fill_report, summary)
    del cubes
    return summary
