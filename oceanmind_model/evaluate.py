"""Score a trained ConvLSTM with the SAME truth, valid-cell mask and metric code as the baselines
(oceanmind_forecast), then write the comparison against persistence and climatology."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from oceanmind_forecast.evaluate import (evaluate_baselines, evaluate_predictions, load_split_truth,
                                         skill_vs_reference)
from oceanmind_preprocess.datasets import ForecastDataset

from .train import load_checkpoint, resolve_device


@torch.no_grad()
def predict_degC(model, root, split, device, batch_size=4, num_workers=0):
    """(N, Hn, H, W) forecasts in degC for every accepted window of `split`, in window-index order."""
    root = Path(root)
    ds = ForecastDataset(root, split)
    stats = json.loads((root / "stats.json").read_text())["channels"][ds.meta["target_channel"]]
    out = []
    model.eval()
    for b in DataLoader(ds, batch_size=batch_size, shuffle=False, num_workers=num_workers):
        out.append(model(b["x"].to(device))[:, :, 0].cpu().numpy())
    p = np.concatenate(out).astype("float32")
    return p * np.float32(stats["std"]) + np.float32(stats["mean"])


def evaluate_model(cfg, checkpoint="best", split="test", out_subdir="model", device=None):
    root = Path(cfg.paths.out_dir)
    dev = resolve_device(device or cfg.training.device)
    model, ck = load_checkpoint(root / out_subdir / f"{checkpoint}_model.pt", dev)
    pred = predict_degC(model, root, split, dev, num_workers=cfg.training.num_workers)
    d = load_split_truth(root, split)
    assert pred.shape == d["y"].shape, (pred.shape, d["y"].shape)
    valid = d["y_valid"] & d["x_last_valid"][:, None]            # identical to evaluate_baselines
    res = evaluate_baselines(root, split)
    m = evaluate_predictions(pred, d["y"], valid, d["horizons"])
    pers = res["baselines"]["persistence"]
    m["mae_skill_vs_persistence"] = skill_vs_reference(m, pers, "mae")
    m["rmse_skill_vs_persistence"] = skill_vs_reference(m, pers, "rmse")
    res["baselines"] = {"convlstm": m, **res["baselines"]}
    res["checkpoint"] = {"which": checkpoint, "epoch": ck.get("epoch"), "val_loss": ck.get("val_loss")}
    mdir = root / out_subdir
    suffix = "" if split == "test" else f"_{split}"
    (mdir / f"model_metrics{suffix}.json").write_text(json.dumps(res, indent=2))
    _csv(res, mdir / f"model_metrics{suffix}.csv")
    _report(res, mdir / f"model_report{suffix}.md")
    return res


def _csv(res, path):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "horizon_days", "mae_degC", "rmse_degC", "r2", "mae_skill_vs_persistence",
                    "rmse_skill_vs_persistence", "n_cells"])
        for n, r in res["baselines"].items():
            for i, h in enumerate(res["horizons"]):
                w.writerow([n, h, r["mae"][i], r["rmse"][i], r["r2"][i], r["mae_skill_vs_persistence"][i],
                            r["rmse_skill_vs_persistence"][i], r["n"][i]])
            w.writerow([n, "mean", r["mean_mae"], r["mean_rmse"], r["mean_r2"], "", "", ""])


def _report(res, path):
    B, hz = res["baselines"], res["horizons"]
    c, p = B["convlstm"], B["persistence"]
    ck = res["checkpoint"]
    L = ["# ConvLSTM vs baselines", "",
         f"- Split **{res['split']}** {res['date_range'][0]} to {res['date_range'][1]}, {res['n_windows']} windows; checkpoint "
         f"`{ck['which']}` (epoch {ck['epoch']}, val loss {ck['val_loss']:.6f}).",
         "- Same truth, same valid-cell mask (ocean cells observed on origin and target day) and same metric code for all three models.",
         "- Skill = 1 - error/error_persistence (positive = better than persistence).", ""]
    for key, lab in (("mae", "MAE (degC)"), ("rmse", "RMSE (degC)"), ("r2", "R²")):
        L += [f"## {lab}", "", "| Horizon | ConvLSTM | Persistence | Climatology |", "|---|---|---|---|"]
        for i, h in enumerate(hz):
            L.append(f"| {h}-day | {c[key][i]:.4f} | {p[key][i]:.4f} | {B['climatology'][key][i]:.4f} |")
        L.append(f"| **mean** | {c['mean_' + key]:.4f} | {p['mean_' + key]:.4f} | {B['climatology']['mean_' + key]:.4f} |")
        L.append("")
    L += ["## ConvLSTM skill vs persistence", "", "| Horizon | MAE skill | RMSE skill |", "|---|---|---|"]
    L += [f"| {h}-day | {c['mae_skill_vs_persistence'][i]:+.3f} | {c['rmse_skill_vs_persistence'][i]:+.3f} |"
          for i, h in enumerate(hz)]
    beats = [h for i, h in enumerate(hz) if c["mae"][i] < p["mae"][i] and c["rmse"][i] < p["rmse"][i]]
    L += ["", "## Verdict", ""]
    if len(beats) == len(hz):
        L.append(f"- ConvLSTM beats persistence on both MAE and RMSE at all horizons (mean MAE {c['mean_mae']:.4f} vs {p['mean_mae']:.4f} degC).")
    elif not beats:
        L.append(f"- ConvLSTM does **not** beat persistence at any horizon (mean MAE {c['mean_mae']:.4f} vs {p['mean_mae']:.4f} degC).")
    else:
        L.append(f"- ConvLSTM beats persistence (MAE and RMSE) only at horizons {beats}; mean MAE {c['mean_mae']:.4f} vs {p['mean_mae']:.4f} degC.")
    L.append(f"- ConvLSTM {'beats' if c['mean_mae'] < B['climatology']['mean_mae'] else 'does not beat'} climatology on mean MAE "
             f"({c['mean_mae']:.4f} vs {B['climatology']['mean_mae']:.4f} degC).")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")
