"""Sensitivity analysis of the trained ConvLSTM forecast for one place: what the forecast does when part of its input is changed.

This is a SENSITIVITY analysis (a counterfactual perturbation of the model's own input window, repeated through the real trained network), not a causal explanation of the
ocean. The perturbation removes the temperature anomaly from part of the input: for the chosen days and cells the SST channel is set to that day's climatological value and
the anomaly channel to zero, i.e. "normal conditions" are shown to the model instead of what was observed. The change this makes to the forecast at the chosen place, in
degrees C, is the sensitivity. Nothing is fitted or invented: every number is a difference between two forward passes of the checkpoint that produced the forecast.

Three views are returned:
  * temporal: removing the anomaly from ONE input day at a time (within a neighbourhood of the place) - which of the 7 days the forecast leans on;
  * local vs all: removing it over the whole 7 days in the neighbourhood, and over the whole domain;
  * spatial: removing it over the whole 7 days in one block at a time around the place - which surrounding area the forecast leans on.
Run through `python -m oceanmind_model explain --config <cfg> --lat <lat> --lon <lon>`; the API calls it as a subprocess so that the API itself never imports PyTorch."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from oceanmind_forecast.evaluate import load_climatology
from oceanmind_preprocess.datasets import ForecastDataset

from .normalisation import ModelSpace
from .train import load_checkpoint, resolve_device

NEIGHBOURHOOD_DEG = 8.0          # the "local" area around the place: +- this many degrees
BLOCK_DEG = 8.0                  # spatial occlusion block size
REACH_BLOCKS = 3                 # blocks either side of the place's block (a 6 x 6 block map)


def explain_cell(cfg, lat: float, lon: float, device: str | None = None, checkpoint: str = "best", split: str = "test", out_subdir: str = "model") -> dict:
    import torch
    root = Path(cfg.paths.out_dir)
    dev = resolve_device(device or cfg.training.device)
    model, ck = load_checkpoint(root / out_subdir / f"{checkpoint}_model.pt", dev)
    ds = ForecastDataset(root, split)
    meta, stats = ds.meta, json.loads((root / "stats.json").read_text())["channels"]
    names = list(ds.channels)
    sst_i, an_i = names.index(meta["target_channel"]), names.index(f"{meta['target_channel']}_anom")
    latv, lonv = np.asarray(meta["lat"], dtype="float64"), np.asarray(meta["lon"], dtype="float64")
    res = float(meta["resolution"])
    origin = float(lonv[0]) - res / 2
    lon_axis = origin + float(np.mod(lon - origin, 360.0))
    i, j = int(np.clip((lat - (latv[0] - res / 2)) // res, 0, len(latv) - 1)), int(np.clip((lon_axis - origin) // res, 0, len(lonv) - 1))
    if ds.land_mask[i, j]:
        raise ValueError("land cell: there is no forecast to explain here")

    x = np.ascontiguousarray(ds.cube[-ds.lookback:][:, ds.ch]).astype("float32")                # (T, C, H, W): the real input window of the latest forecast
    T = x.shape[0]
    dates = pd.DatetimeIndex(np.load(root / "cubes" / f"{split}_dates.npy"))[-T:]
    clim = load_climatology(root)[dates.dayofyear.to_numpy() - 1]                              # (T, H, W) degC
    s_sst, s_an = stats[names[sst_i]], stats[names[an_i]]
    normal_sst = ((clim - s_sst["mean"]) / s_sst["std"]).astype("float32")                      # what "normal" SST looks like to the model (normalised)
    normal_an = np.float32((0.0 - s_an["mean"]) / s_an["std"])
    ocean = ~ds.land_mask

    def perturbed(days, region):
        """The window with the anomaly removed on `days` (indices) inside `region` (bool H x W)."""
        z = x.copy()
        m = region & ocean
        for d in days:
            z[d, sst_i][m] = normal_sst[d][m]
            z[d, an_i][m] = normal_an
        return z

    la = latv[:, None] * np.ones((1, len(lonv)))
    dlon = np.abs(((lonv[None, :] - lon_axis + 180.0) % 360.0) - 180.0) * np.ones((len(latv), 1))
    local = (np.abs(la - latv[i]) <= NEIGHBOURHOOD_DEG) & (dlon <= NEIGHBOURHOOD_DEG)
    everywhere = np.ones_like(local)
    runs = [("base", x)]
    for d in range(T):
        runs.append((f"day{d}", perturbed([d], local)))
    runs.append(("local_all_days", perturbed(range(T), local)))
    runs.append(("everywhere_all_days", perturbed(range(T), everywhere)))
    # spatial blocks of BLOCK_DEG around the place, aligned to the grid of blocks that contains it
    bi0, bj0 = int((latv[i] - latv[0]) // BLOCK_DEG), int(((lonv[j] - lonv[0]) % 360.0) // BLOCK_DEG)
    lat_edges = [float(latv[0] + (bi0 + k) * BLOCK_DEG) for k in range(-REACH_BLOCKS, REACH_BLOCKS + 1)]
    lon_edges = [float(lonv[0] + (bj0 + k) * BLOCK_DEG) for k in range(-REACH_BLOCKS, REACH_BLOCKS + 1)]
    blocks = []
    for a in range(2 * REACH_BLOCKS):
        for b in range(2 * REACH_BLOCKS):
            la0, la1 = lat_edges[a], lat_edges[a + 1]
            lo0, lo1 = lon_edges[b], lon_edges[b + 1]
            dl = ((lonv[None, :] - lo0) % 360.0)
            region = (la >= la0) & (la < la1) & (dl < (lo1 - lo0))
            blocks.append((a, b, region if (region & ocean).any() else None))
            runs.append((f"block{a}_{b}", perturbed(range(T), region)))
    space = ModelSpace(root, out_subdir, names, meta["target_channel"])                         # the checkpoint's own number scale (see normalisation.py)
    with torch.no_grad():
        batch = torch.from_numpy(space.convert(np.stack([r[1] for r in runs]), names)).to(dev)
        out = np.concatenate([model(batch[k:k + 16])[:, :, 0, i, j].cpu().numpy() for k in range(0, len(runs), 16)])          # (runs, horizons) normalised SST at the place
    sd, mu = s_sst["std"], s_sst["mean"]                                                        # the dataset's scale, for reading the input window back in degC
    deg = space.to_degC(out)
    base = deg[0]
    delta = deg[1:] - base[None, :]                                                             # change in the forecast (degC) caused by each perturbation
    index = {r[0]: k for k, r in enumerate(runs[1:])}
    n_h = base.shape[0]
    spatial = np.full((n_h, 2 * REACH_BLOCKS, 2 * REACH_BLOCKS), np.nan, dtype="float32")
    for a, b, region in blocks:
        if region is not None:                                                                   # a block without ocean cells has no sensitivity (left empty, never 0)
            spatial[:, a, b] = delta[index[f"block{a}_{b}"]]
    own_block = [(a, b) for a, b, region in blocks if region is not None and region[i, j]]
    last = x[-1]
    return {
        "cell": {"lat": float(latv[i]), "lon": float(lonv[j]), "row": i, "col": j},
        "input_window": {"dates": [str(d.date()) for d in dates], "channels": names, "days": int(T),
                         "sst_c": [float(x[d, sst_i, i, j] * sd + mu) for d in range(T)], "climatology_c": [float(clim[d, i, j]) for d in range(T)],
                         "anomaly_c": [float(x[d, an_i, i, j] * s_an["std"] + s_an["mean"]) for d in range(T)]},
        "forecast_c": [float(v) for v in base],
        "persistence_c": float(last[sst_i, i, j] * sd + mu),
        "checkpoint": {"which": checkpoint, "epoch": ck.get("epoch"), "val_loss": ck.get("val_loss"), "model_cfg": ck.get("model_cfg"), "input_scale": space.source},
        "parameters": int(sum(p.numel() for p in model.parameters())),
        "sensitivity": {
            "method": "anomaly-removal sensitivity (input perturbation through the trained ConvLSTM)",
            "reading": "Each number is how many degrees C the observed temperature anomaly in the stated part of the input contributes to the forecast at this place (forecast minus the forecast with that part replaced by normal, climatological conditions). "
                       "Positive = the observed anomaly there pushes the forecast warmer. It describes what the trained model responds to; it does not show a physical cause.",
            "neighbourhood_deg": NEIGHBOURHOOD_DEG, "block_deg": BLOCK_DEG,
            "temporal": {"days": [str(d.date()) for d in dates], "delta_c": [[-float(delta[index[f"day{d}"], h]) for h in range(n_h)] for d in range(T)]},
            "local_all_days_c": [-float(v) for v in delta[index["local_all_days"]]],
            "everywhere_all_days_c": [-float(v) for v in delta[index["everywhere_all_days"]]],
            "spatial": {"lat_edges": lat_edges, "lon_edges": lon_edges, "delta_c": [[[None if not np.isfinite(spatial[h, a, b]) else -float(spatial[h, a, b]) for b in range(2 * REACH_BLOCKS)]
                                                                                      for a in range(2 * REACH_BLOCKS)] for h in range(n_h)], "own_block": own_block[0] if own_block else None},
        },
    }
