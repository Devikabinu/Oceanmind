"""Benchmark data preparation (ADD-ON: reads nothing from, and writes nothing to, the project's processed/ or config files).

    scripts/benchmark/.venv/bin/python scripts/benchmark/prepare_data.py [--source erddap|psl] [--end YYYY-MM-DD]

1. Downloads NOAA OISST v2.1 daily SST for the benchmark box, 2012-01-01 .. latest FINAL day (history is used ONLY for the day-of-year climatology).
   erddap = the project's own downloader (oceanmind_preprocess.ingest, FINAL product); psl = NOAA PSL OPeNDAP mirror (fallback, see data_meta.json).
2. Takes the most recent 2 years as ONE continuous block and splits it chronologically 75 / 12 / 13 % (train / val / test).
3. Builds exactly the project's 6 forecast channels with the project's own functions (gap filling, clipping, climatology, anomaly,
   gradient, day-of-year, mask), z-scores with TRAIN-block statistics only, and indexes the 7-day -> 1..7-day forecast windows.

Output: processed/benchmark/data/benchmark_dataset.npz and data_meta.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from oceanmind_preprocess import features, normalize  # noqa: E402
from oceanmind_preprocess.clean import preclean  # noqa: E402
from oceanmind_preprocess.config import load_config  # noqa: E402
from oceanmind_preprocess.missing import compute_limits  # noqa: E402

BASE = ROOT / "processed" / "benchmark"
OUT = BASE / os.environ.get("BENCH_SUBDIR", "")             # follow-up runs write to a sub-folder, phase-1 results are never overwritten
BCFG = yaml.safe_load((ROOT / "scripts" / "benchmark" / os.environ.get("BENCH_CONFIG", "benchmark_config.yaml")).read_text())
NATIVE_RES = 0.25


def region_cell_centres():
    r = BCFG["region"]
    lat = np.arange(r["lat_min"] + NATIVE_RES / 2, r["lat_max"], NATIVE_RES)
    lon = np.arange(r["lon_min"] + NATIVE_RES / 2, r["lon_max"], NATIVE_RES)
    return lat, lon


# ----------------------------------------------------------------------------- download
def fetch_erddap(end_override=None):
    from oceanmind_preprocess import ingest
    cfg = load_config(ROOT / "config.yaml")
    cfg.paths.raw_dir = str(BASE / "raw")                       # benchmark's own cache; the project's data/ is never touched
    lat, lon = region_cell_centres()
    cfg.grid.update(lat_min=float(lat[0]), lat_max=float(lat[-1]), lon_min=float(lon[0]), lon_max=float(lon[-1]))
    info = ingest.endpoint_info(cfg, "final")
    end = pd.Timestamp(end_override) if end_override else info["latest"]
    start = pd.Timestamp(BCFG["data"]["history_start"])
    print(f"ERDDAP FINAL product {info['dataset']}: server latest day {info['latest'].date()}; using {start.date()} .. {end.date()}")
    _, cache = ingest.paths(cfg)
    pieces = []
    for y in range(start.year, end.year + 1):
        t0, t1 = max(start, pd.Timestamp(y, 1, 1)), min(end, pd.Timestamp(y, 12, 31))
        dest = cache / f"final_{t0:%Y-%m-%d}_{t1:%Y-%m-%d}.nc"
        if not dest.exists():
            print(f"  downloading {t0.date()} .. {t1.date()}")
            ingest.fetch_range(cfg, "final", t0, t1, name=dest.name)
        else:
            print(f"  cached      {t0.date()} .. {t1.date()}")
        pieces.append(dest)
    das = [xr.open_dataset(p)["sst"].squeeze("zlev", drop=True).rename(latitude="lat", longitude="lon").load() for p in pieces]
    sst = xr.concat(das, dim="time")
    meta = {"source": "erddap", "product": "NOAA OISST v2.1 FINAL", "dataset": info["dataset"], "host": cfg.ingest.sst.products["final"]["host"],
            "server_latest_final_day": str(info["latest"].date()), "downloaded_files": [p.name for p in pieces]}
    return sst, end, meta


def fetch_psl(end_override):
    r = BCFG["region"]
    start = pd.Timestamp(BCFG["data"]["history_start"])
    end = pd.Timestamp(end_override)
    parts = []
    cache = BASE / "raw" / "psl"
    cache.mkdir(parents=True, exist_ok=True)
    for y in range(start.year, end.year + 1):
        url = f"https://psl.noaa.gov/thredds/dodsC/Datasets/noaa.oisst.v2.highres/sst.day.mean.{y}.nc"
        ds = None                                               # remote file opened lazily, only if a month is not cached
        for m in range(1, 13):                                  # month-sized reads: year-sized OPeNDAP reads fail on this server
            t0, t1 = pd.Timestamp(y, m, 1), pd.Timestamp(y, m, 1) + pd.offsets.MonthEnd(0)
            if t0 > end or t1 < start:
                continue
            f = cache / f"psl_{y}-{m:02d}.nc"
            if not f.exists():
                for attempt in range(1, 6):
                    try:
                        ds = ds if ds is not None else xr.open_dataset(url)
                        sub = ds["sst"].sel(time=slice(t0, t1), lat=slice(r["lat_min"], r["lat_max"]), lon=slice(r["lon_min"] % 360, r["lon_max"] % 360)).load()
                        break
                    except (RuntimeError, OSError) as e:
                        print(f"    {y}-{m:02d} attempt {attempt} failed ({e}); retrying")
                        time.sleep(2 * attempt)
                else:
                    raise RuntimeError(f"PSL OPeNDAP kept failing for {y}-{m:02d}")
                sub.to_netcdf(f)
            sub = xr.open_dataarray(f).load()
            parts.append(sub.assign_coords(lon=((sub.lon + 180) % 360) - 180))
        print(f"  read {y} from {url}")
    sst = xr.concat(parts, dim="time").sel(time=slice(start, end))
    meta = {"source": "psl", "product": "NOAA OISST v2.1 (PSL OPeNDAP mirror)", "host": "https://psl.noaa.gov/thredds",
            "note": "fallback source used because the ERDDAP FINAL server was unavailable; PSL does not label preliminary days"}
    return sst, end, meta


# ----------------------------------------------------------------------------- build
def build(sst_native: xr.DataArray, end: pd.Timestamp, source_meta: dict):
    d = BCFG["data"]
    cfg = load_config(ROOT / "config.yaml")                    # only for feature / missing-data settings (read, never written)
    coarsen = BCFG["region"]["coarsen"]
    res = NATIVE_RES * coarsen
    cfg.grid.resolution = res

    times_all = pd.date_range(BCFG["data"]["history_start"], end, freq="D")
    sst_native = sst_native.reindex(time=times_all)             # missing server days stay NaN (filled below if <= 3 days)
    lat_n, lon_n = region_cell_centres()
    sst_native = sst_native.sel(lat=lat_n, lon=lon_n, method="nearest")
    c = sst_native.coarsen(lat=coarsen, lon=coarsen, boundary="exact").mean(skipna=False)
    sst = c.values.astype("float32")                            # (T,H,W) degC
    lat, lon = c.lat.values, c.lon.values
    T, H, W = sst.shape
    ocean = ~np.all(np.isnan(sst), axis=0)
    print(f"grid {H} x {W} at {res} deg, {int(ocean.sum())} ocean cells of {H * W}; {T} days {times_all[0].date()}..{times_all[-1].date()}")

    # --- the benchmark block: most recent 2 years, one continuous run, chronological split -------------------
    if "window_days" in d:
        w_start = end - pd.Timedelta(days=d["window_days"]) + pd.Timedelta(days=1)
    else:
        w_start = end - pd.DateOffset(years=d["window_years"]) + pd.Timedelta(days=1)
    wlo = int(times_all.searchsorted(w_start))
    N = T - wlo
    if "test_days" in d:
        n_te, n_va = d["test_days"], d["val_days"]
        n_tr = N - n_va - n_te
    else:
        n_tr, n_va = round(d["split"]["train"] * N), round(d["split"]["val"] * N)
        n_te = N - n_tr - n_va
    sl = {"history": slice(0, wlo), "train": slice(wlo, wlo + n_tr), "val": slice(wlo + n_tr, wlo + n_tr + n_va), "test": slice(wlo + n_tr + n_va, T)}
    for k, s in sl.items():
        print(f"  {k:<7}{s.stop - s.start:>6} days  {times_all[s.start].date()} .. {times_all[s.stop - 1].date()}")

    # --- project cleaning: land->NaN, clip to TRAIN-block percentile limits, fill gaps <= 3 days inside each segment ------
    limits = {"sst": compute_limits(sst[sl["train"]], ocean, d["clip_percentiles"])}
    clean, fill_report = preclean(cfg, {"sst": sst}, ocean, limits, [sl["history"], sl["train"], sl["val"], sl["test"]])
    clean = clean["sst"]
    print("  gap fill:", {k: round(v, 3) if isinstance(v, float) else v for k, v in fill_report["sst"].items() if k.startswith("pct")})

    # --- climatology from days strictly BEFORE the validation block (history + train block): no val/test leakage ----------
    n_clim = sl["val"].start
    _, clim = features.daily_climatology(clean[:n_clim], times_all[:n_clim], d["clim_sigma_days"])
    clim_n_years = float((n_clim) / 365.25)

    # --- the project's 6 forecast channels on the benchmark block, z-score with TRAIN statistics only ------------------
    tw = times_all[wlo:]
    data = {"sst": clean[wlo:]}
    cube, names = features.assemble_features(cfg, data, tw, lat, {"sst": clim})
    tr = slice(0, n_tr)
    stats = normalize.fit_stats(cube, names, tr, ocean, cfg.normalization.min_std)
    raw_sst = clean[wlo:].copy()
    normalize.zscore(cube, names, stats)
    normalize.finish(cube, ocean)

    # --- forecast windows per split (same rule as oceanmind_preprocess.windows.forecast_index) ---------------------------
    hz = np.asarray(d["horizons"])
    L = d["lookback_days"]
    miss = 1.0 - np.nanmean(np.where(ocean, ~np.isnan(clean[wlo:]), np.nan), axis=(1, 2))   # missing ocean fraction per day (after gap filling)
    rel = {"train": (0, n_tr), "val": (n_tr, n_tr + n_va), "test": (n_tr + n_va, N)}
    starts = {}
    for name, (a, b) in rel.items():
        keep, skipped = [], 0
        for s in range(a, b - (L + hz.max()) + 1):
            tgt = s + L - 1 + hz
            if np.mean(np.concatenate([miss[s:s + L], miss[tgt]])) > d["max_nan_frac"]:
                skipped += 1
                continue
            keep.append(s)
        starts[name] = np.asarray(keep, dtype=np.int32)
        print(f"  windows {name:<5}{len(keep):>5} (skipped {skipped})")

    ocean_mask = ocean.astype("float32")
    np.savez_compressed(OUT / "data" / "benchmark_dataset.npz", cube=cube.astype("float32"), raw_sst=raw_sst, ocean=ocean_mask, clim=clim,
                        times=np.asarray(tw.strftime("%Y-%m-%d")), lat=lat, lon=lon, channels=np.asarray(names),
                        starts_train=starts["train"], starts_val=starts["val"], starts_test=starts["test"],
                        split_bounds=np.asarray([[a, b] for a, b in rel.values()]), horizons=hz, lookback=L)
    meta = {
        "prepared_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source_meta,
        "region": {**BCFG["region"], "native_resolution_deg": NATIVE_RES, "resolution_deg": res, "grid_hw": [H, W], "n_ocean_cells": int(ocean.sum()),
                   "lat_range": [float(lat[0]), float(lat[-1])], "lon_range": [float(lon[0]), float(lon[-1])]},
        "history": {"start": str(times_all[0].date()), "end": str(times_all[wlo - 1].date()), "used_for": "day-of-year climatology only (never as training windows)"},
        "benchmark_block": {"start": str(tw[0].date()), "end": str(tw[-1].date()), "days": int(N), "continuous": True},
        "split_days": {"train": int(n_tr), "val": int(n_va), "test": int(n_te)},
        "split_dates": {k: [str(times_all[sl[k].start].date()), str(times_all[sl[k].stop - 1].date())] for k in ("train", "val", "test")},
        "split_fractions": {"train": n_tr / N, "val": n_va / N, "test": n_te / N},
        "windows": {k: int(len(v)) for k, v in starts.items()},
        "lookback_days": L, "horizons": hz.tolist(), "channels": list(names),
        "normalisation": {"fitted_on": "train block only", "stats": {k: {"mean": v["mean"], "std": v["std"]} for k, v in stats.items()}},
        "climatology": {"fitted_on": f"{times_all[0].date()}..{times_all[n_clim - 1].date()} (history + train block, everything before validation)",
                        "smooth_sigma_days": d["clim_sigma_days"], "approx_years_of_data": round(clim_n_years, 2)},
        "clip_limits_degC": limits["sst"], "gap_fill": {k: v for k, v in fill_report["sst"].items()},
        "test_season_coverage_note": f"test block covers {times_all[sl['test'].start].date()} .. {times_all[sl['test'].stop - 1].date()} only",
    }
    (OUT / "data" / "data_meta.json").write_text(json.dumps(meta, indent=2, default=float))
    return meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["erddap", "psl"], default="erddap")
    ap.add_argument("--end", default=None, help="last day to use (default: the latest FINAL day the server has; required for psl)")
    a = ap.parse_args()
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    if a.source == "erddap":
        sst, end, meta = fetch_erddap(a.end)
    else:
        if not a.end:
            ap.error("--end is required with --source psl")
        sst, end, meta = fetch_psl(a.end)
    print(json.dumps({k: v for k, v in build(sst, end, meta).items() if k in ("benchmark_block", "split_dates", "windows")}, indent=1))


if __name__ == "__main__":
    main()
