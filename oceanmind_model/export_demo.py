"""Export the dashboard's forecast snapshot: run the best ConvLSTM on the LAST accepted test window and save
the gridded forecast next to the observed truth, the climatology and a daily domain-mean history.

Written to processed/<out_subdir>/dashboard/ (snapshot.npz + snapshot.json). The FastAPI backend serves these
files; it never imports torch. Everything here is model output or observed/processed data -- nothing synthetic."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from oceanmind_forecast.evaluate import load_climatology, load_split_truth
from oceanmind_forecast.baselines import climatology_forecast
from oceanmind_preprocess.datasets import ForecastDataset

from .train import load_checkpoint, resolve_device


def export_dashboard_snapshot(cfg, checkpoint="best", split="test", out_subdir="model", device=None):
    import torch
    root = Path(cfg.paths.out_dir)
    dev = resolve_device(device or cfg.training.device)
    model, ck = load_checkpoint(root / out_subdir / f"{checkpoint}_model.pt", dev)

    ds = ForecastDataset(root, split)
    i = len(ds) - 1                                              # most recent window of the split
    stats = json.loads((root / "stats.json").read_text())["channels"][ds.meta["target_channel"]]
    with torch.no_grad():
        p = model(ds[i]["x"][None].to(dev))[0, :, 0].cpu().numpy()
    pred = p * np.float32(stats["std"]) + np.float32(stats["mean"])        # (Hn,H,W) degC

    d = load_split_truth(root, split)
    ocean = d["ocean"]
    clim_all = load_climatology(root)
    tdates = d["target_dates"][i]                                          # (Hn,)
    clim = climatology_forecast(clim_all, tdates[None])[0]
    nan = np.float32(np.nan)

    def land_nan(a):
        return np.where(ocean, a, nan).astype("float32")

    # input window (last 7 observed days) and the whole-split daily domain mean, for trend charts
    meta = json.loads((root / "meta.json").read_text())
    names = meta["channels"]
    cube = np.load(root / "cubes" / f"{split}.npy", mmap_mode="r")
    dates = pd.DatetimeIndex(np.load(root / "cubes" / f"{split}_dates.npy"))
    sst_ch = names.index(meta["target_channel"])
    msk_ch = names.index(f"mask_{meta['target_channel']}")
    all_sst = np.asarray(cube[:, sst_ch], dtype="float32") * np.float32(stats["std"]) + np.float32(stats["mean"])
    all_ok = (np.asarray(cube[:, msk_ch]) > 0.5) & ocean
    all_clim = clim_all[dates.dayofyear.to_numpy() - 1]
    cnt = all_ok.sum(axis=(1, 2)).clip(min=1)
    daily_mean = (np.where(all_ok, all_sst, 0).sum(axis=(1, 2)) / cnt).astype("float32")
    daily_clim = (np.where(all_ok, all_clim, 0).sum(axis=(1, 2)) / cnt).astype("float32")

    last_day = pd.Timestamp(d["input_end_dates"][i])
    last_idx = int(dates.get_loc(last_day))
    obs_last = land_nan(np.where(all_ok[last_idx], all_sst[last_idx], nan))
    obs_clim = all_clim[last_idx]

    # LATEST forecast: the same model run on the final 7 processed days (no truth exists yet for its targets)
    x_latest = torch.from_numpy(np.ascontiguousarray(ds.cube[-ds.lookback:][:, ds.ch]))[None].to(dev)
    with torch.no_grad():
        p2 = model(x_latest)[0, :, 0].cpu().numpy()
    fc_latest = p2 * np.float32(stats["std"]) + np.float32(stats["mean"])
    obs_day = pd.Timestamp(dates[-1])
    latest_targets = obs_day + pd.to_timedelta(np.asarray(d["horizons"]), unit="D")
    latest_clim = climatology_forecast(clim_all, latest_targets.to_numpy()[None])[0]
    nrt = np.load(root / "cubes" / f"{split}_nrt.npy")
    n_nrt_latest = int(np.asarray(nrt[-ds.lookback:]).reshape(ds.lookback, -1).any(axis=1).sum()) if nrt.ndim > 1 else int(nrt[-ds.lookback:].sum())
    latest_obs = land_nan(np.where(all_ok[-1], all_sst[-1], nan))

    out = root / out_subdir / "dashboard"
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out / "snapshot.npz",
        lat=np.asarray(meta["lat"], dtype="float32"), lon=np.asarray(meta["lon"], dtype="float32"),
        ocean=ocean,
        forecast=land_nan(pred), truth=land_nan(np.where(d["y_valid"][i], d["y"][i], nan)),
        climatology=land_nan(clim), observed_last=obs_last, climatology_last=land_nan(obs_clim),
        latest_forecast=land_nan(fc_latest), latest_climatology=land_nan(latest_clim), latest_obs=latest_obs,
        latest_obs_climatology=land_nan(all_clim[-1]),
        daily_mean=daily_mean, daily_clim=daily_clim, daily_dates=np.asarray(dates.strftime("%Y-%m-%d").tolist(), dtype="U10"),
    )
    info = {
        "split": split,
        "model": "ConvLSTM (2 layers, 32 hidden channels)",
        "checkpoint": {"which": checkpoint, "epoch": ck.get("epoch"), "val_loss": ck.get("val_loss")},
        "input_end_date": str(last_day.date()),
        "target_dates": [str(pd.Timestamp(t).date()) for t in tdates],
        "horizons": d["horizons"],
        "grid": {"n_lat": len(meta["lat"]), "n_lon": len(meta["lon"]), "resolution_deg": meta["resolution"]},
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": "hindcast",
        "latest": {
            "observed_date": str(obs_day.date()),
            "target_dates": [str(t.date()) for t in latest_targets],
            "n_nrt_input_days": n_nrt_latest,
            "note": "Operational-style forecast issued from the last processed day. Its targets have no observations yet.",
        },
        "note": ("Forecast issued from the final window of the held-out test period; the observed truth for "
                 "every horizon is known, so it is shown alongside. This is an evaluation snapshot, not a live forecast."),
    }
    (out / "snapshot.json").write_text(json.dumps(info, indent=2))
    from .heatwaves import compute_heatwaves
    info["heatwave"] = compute_heatwaves(root, forecast_latest=land_nan(fc_latest), out_subdir=out_subdir)["latest_date"]
    return info
