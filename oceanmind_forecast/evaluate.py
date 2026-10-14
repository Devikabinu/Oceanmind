"""Load the existing processed test split, run baselines, score them. `evaluate_predictions` is the entry point
a future ConvLSTM should call with its own (N, n_horizons, H, W) degC predictions.

Leakage rules: the test split is only used as truth (and as the persistence input, which is observed data
before the forecast origin). Climatology and the de-normalisation constants come from TRAIN-only artefacts
(processed/climatology.zarr, processed/stats.json)."""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from .baselines import climatology_forecast, persistence_forecast
from .metrics import calculate_metrics


def load_climatology(out_dir, var="sst") -> np.ndarray:
    import xarray as xr
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = xr.open_zarr(Path(out_dir) / "climatology.zarr")
        return np.asarray(ds[var].sel(dayofyear=np.arange(1, 367)).values, dtype="float32")


def load_split_truth(out_dir, split="test") -> dict:
    """Read the processed cube for `split` and return degC fields for every accepted forecast window.
    Keys: x_last (N,H,W) last input SST; y (N,Hn,H,W) target SST; x_last_valid / y_valid (bool, observed or
    gap-filled ocean cells); target_dates (N,Hn); ocean (H,W); horizons; input_end_dates."""
    out = Path(out_dir)
    meta = json.loads((out / "meta.json").read_text())
    stats = json.loads((out / "stats.json").read_text())
    tc = meta["target_channel"]
    names = meta["channels"]
    mu, sd = stats["channels"][tc]["mean"], stats["channels"][tc]["std"]
    cube = np.load(out / "cubes" / f"{split}.npy", mmap_mode="r")
    dates = pd.DatetimeIndex(np.load(out / "cubes" / f"{split}_dates.npy"))
    sst = np.asarray(cube[:, names.index(tc)], dtype="float32") * np.float32(sd) + np.float32(mu)   # (T,H,W) degC
    msk = np.asarray(cube[:, names.index(f"mask_{tc}")]) > 0.5
    ocean = ~np.load(out / "land_mask.npy")
    idx = pd.read_parquet(out / "forecast" / f"windows_{split}.parquet")
    s = idx["start_idx"].to_numpy()
    hz = np.asarray(meta["horizons"])
    last = s + meta["lookback_days"] - 1
    tgt = last[:, None] + hz[None, :]                                               # (N,Hn)
    return {
        "x_last": sst[last], "x_last_valid": msk[last] & ocean,
        "y": sst[tgt], "y_valid": msk[tgt] & ocean,
        "target_dates": dates.to_numpy()[tgt], "input_end_dates": dates[last],
        "ocean": ocean, "horizons": hz.tolist(), "split": split,
        "date_range": (str(dates[0].date()), str(dates[-1].date())),
    }


def evaluate_predictions(pred, truth, valid, horizons=None) -> dict:
    """Score any (N, Hn, H, W) degC forecast. Adds mean MAE/RMSE/R2 over horizons."""
    m = calculate_metrics(pred, truth, valid, horizons)
    m["mean_mae"], m["mean_rmse"], m["mean_r2"] = (float(np.nanmean(m[k])) for k in ("mae", "rmse", "r2"))
    return m


def skill_vs_reference(metrics, ref, key) -> list:
    """Skill score 1 - err/err_ref per horizon (positive = better than the reference; MAE/RMSE only)."""
    return [1.0 - a / b if b else float("nan") for a, b in zip(metrics[key], ref[key])]


def evaluate_baselines(out_dir, split="test", return_predictions=False):
    """Persistence and climatology on `split`, scored on identical cells: ocean cells observed on both the
    forecast-origin day and the target day (so the two baselines are compared like for like)."""
    d = load_split_truth(out_dir, split)
    Hn = len(d["horizons"])
    valid = d["y_valid"] & d["x_last_valid"][:, None]
    preds = {
        "persistence": persistence_forecast(d["x_last"], Hn),
        "climatology": climatology_forecast(load_climatology(out_dir), d["target_dates"]),
    }
    res = {n: evaluate_predictions(p, d["y"], valid, d["horizons"]) for n, p in preds.items()}
    pers = res["persistence"]
    for r in res.values():
        r["mae_skill_vs_persistence"] = skill_vs_reference(r, pers, "mae")
        r["rmse_skill_vs_persistence"] = skill_vs_reference(r, pers, "rmse")
    out = {"split": split, "date_range": d["date_range"], "n_windows": int(d["y"].shape[0]),
           "horizons": d["horizons"], "n_valid_cells": int(valid.sum()), "baselines": res}
    return (out, preds, d) if return_predictions else out
