"""Train and score CNN-only, LSTM-only and the project's ConvLSTM (hybrid) under identical conditions, 3 seeds each.

    python scripts/benchmark/run_benchmark.py --speed-test     # one epoch per model, prints the estimated total time, trains nothing else
    python scripts/benchmark/run_benchmark.py                  # full run; resumable (finished model/seed runs are skipped)

Identical for all models: data, 7-day window, horizons 1..7, chronological split, train-only normalisation, optimiser (AdamW), constant
learning rate, batch size, max epochs, early stopping on VALIDATION loss, masked-MSE loss, gradient clipping, seeds. The model with the best
validation loss is scored on the TEST block (touched only after training ends). Nothing is tuned after seeing test results.
Metrics reuse oceanmind_forecast.metrics.calculate_metrics (the project's own MAE / RMSE code).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models import build_all, n_params  # noqa: E402
from oceanmind_forecast.metrics import calculate_metrics  # noqa: E402  (existing code, not modified)
from oceanmind_model.losses import masked_loss  # noqa: E402  (existing code, not modified)

BASE = ROOT / "processed" / "benchmark"
OUT = BASE / os.environ.get("BENCH_SUBDIR", "")             # follow-up runs write to a sub-folder, phase-1 results are never overwritten
BCFG = yaml.safe_load((ROOT / "scripts" / "benchmark" / os.environ.get("BENCH_CONFIG", "benchmark_config.yaml")).read_text())
TC = BCFG["training"]


def pick_device(force=None):
    if force:
        return torch.device(force)
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def seed_all(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class Data:
    """The prepared benchmark block, kept on the compute device (it is only a few tens of MB)."""

    def __init__(self, device):
        z = np.load(OUT / "data" / "benchmark_dataset.npz", allow_pickle=True)
        self.meta = json.loads((OUT / "data" / "data_meta.json").read_text())
        self.names = [str(c) for c in z["channels"]]
        self.sst_ch, self.mask_ch = self.names.index("sst"), self.names.index("mask_sst")
        self.cube_np = z["cube"]
        self.cube = torch.from_numpy(self.cube_np).to(device)
        self.raw_sst = z["raw_sst"]
        self.clim = z["clim"]
        self.ocean = z["ocean"] > 0.5
        self.times = pd.DatetimeIndex(z["times"])
        self.lat, self.lon = z["lat"], z["lon"]
        self.starts = {k: z[f"starts_{k}"] for k in ("train", "val", "test")}
        self.L, self.hz = int(z["lookback"]), z["horizons"]
        self.H, self.W = self.cube.shape[-2:]
        self.C = self.cube.shape[1]
        st = self.meta["normalisation"]["stats"]["sst"]
        self.mu, self.sd = st["mean"], st["std"]
        self.device = device
        self.ocean_t = torch.from_numpy(self.ocean).to(device)
        self.hz_t = torch.from_numpy(np.asarray(self.hz)).to(device)

    def batch(self, starts):
        s = torch.as_tensor(starts, device=self.device, dtype=torch.long)
        xi = s[:, None] + torch.arange(self.L, device=self.device)[None]
        x = self.cube[xi]                                              # (B, L, C, H, W)
        ti = s[:, None] + self.L - 1 + self.hz_t[None]
        y = self.cube[ti, self.sst_ch]                                 # (B, Hn, H, W) normalised SST
        m = (self.cube[ti, self.mask_ch] > 0.5) & self.ocean_t[None, None]
        return x, y, m


def run_epoch(model, data, starts, opt, bs, gen, train):
    model.train(train)
    idx = np.asarray(starts)
    if train:
        idx = idx[torch.randperm(len(idx), generator=gen).numpy()]
    tot = n = 0
    with torch.set_grad_enabled(train):
        for a in range(0, len(idx), bs):
            x, y, m = data.batch(idx[a:a + bs])
            loss = masked_loss(model(x)[:, :, 0], y, m, TC["loss"])
            if train:
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), TC["grad_clip"])
                opt.step()
            k = len(idx[a:a + bs])
            tot += float(loss.detach()) * k
            n += k
    return tot / max(n, 1)


def fit(model, data, seed, device, max_epochs=None, log=print):
    """Train on TRAIN windows, early-stop on VALIDATION loss, return the best-validation weights. The test block is not used here."""
    seed_all(seed)
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=TC["learning_rate"], weight_decay=TC["weight_decay"])   # constant LR, as in the project
    gen = torch.Generator().manual_seed(seed)
    best, best_state, best_ep, bad = float("inf"), None, 0, 0
    hist = {"train_loss": [], "val_loss": [], "epoch_seconds": []}
    t_all = time.time()
    for ep in range(1, (max_epochs or TC["max_epochs"]) + 1):
        t0 = time.time()
        tl = run_epoch(model, data, data.starts["train"], opt, TC["batch_size"], gen, True)
        vl = run_epoch(model, data, data.starts["val"], None, TC["batch_size"], gen, False)
        if device.type == "mps":
            torch.mps.synchronize()
        hist["train_loss"].append(tl); hist["val_loss"].append(vl); hist["epoch_seconds"].append(time.time() - t0)
        if vl < best:
            best, best_ep, bad = vl, ep, 0
            best_state = copy.deepcopy({k: v.detach().cpu() for k, v in model.state_dict().items()})
        else:
            bad += 1
        log(f"    epoch {ep:>2} train {tl:.5f} val {vl:.5f} ({hist['epoch_seconds'][-1]:.1f}s){' *' if bad == 0 else ''}")
        if bad >= TC["patience"]:
            break
    model.load_state_dict(best_state)
    return model, {**hist, "best_val_loss": best, "best_epoch": best_ep, "epochs_run": ep, "train_seconds": time.time() - t_all}


# ----------------------------------------------------------------------------- evaluation (TEST block only)
def acc(pred, truth, clim_t, valid):
    """Anomaly correlation per horizon, pooled over all test windows and cells: sum(fa*oa) / sqrt(sum(fa^2) * sum(oa^2)),
    anomalies taken against the train-period day-of-year climatology (the project's own climatology code)."""
    fa, oa = (pred - clim_t).astype("float64"), (truth - clim_t).astype("float64")
    out = []
    for h in range(pred.shape[1]):
        v = valid[:, h] & np.isfinite(fa[:, h]) & np.isfinite(oa[:, h])
        f, o = fa[:, h][v], oa[:, h][v]
        den = np.sqrt((f ** 2).sum() * (o ** 2).sum())
        out.append(float((f * o).sum() / den) if den > 0 else float("nan"))
    return out


def truth_and_masks(data, split="test"):
    s = data.starts[split]
    last = s + data.L - 1
    tgt = last[:, None] + data.hz[None, :]
    y = data.raw_sst[tgt]                                              # (N, Hn, H, W) degC
    m = data.cube_np[:, data.mask_ch] > 0.5
    valid = m[tgt] & data.ocean[None, None] & m[last][:, None] & data.ocean[None, None]
    clim_t = data.clim[data.times[tgt.ravel()].dayofyear.values.reshape(tgt.shape) - 1]           # (N, Hn, H, W) climatology on each target date
    return {"y": y, "valid": valid, "last": data.raw_sst[last], "clim_t": clim_t, "tgt": tgt, "starts": s}


SEASONS = {"DJF": (12, 1, 2), "MAM": (3, 4, 5), "JJA": (6, 7, 8), "SON": (9, 10, 11)}     # meteorological seasons, by forecast-origin month


def seasonal(pred, T, data, hz):
    """Test metrics per season (grouped by the month of the last input day), so a single season cannot decide the result."""
    mon = data.times[T["starts"] + data.L - 1].month.values
    n = len(T["starts"])
    out = {}
    for name, months in SEASONS.items():
        idx = np.where(np.isin(mon, months))[0]
        if len(idx) == 0:
            continue
        sub = {k: (v[idx] if isinstance(v, np.ndarray) and v.shape[:1] == (n,) else v) for k, v in T.items()}
        m = score(pred[idx], sub, hz)
        out[name] = {"n_windows": int(len(idx)), "mean_rmse": m["mean_rmse"], "mean_mae": m["mean_mae"], "mean_acc": m["mean_acc"], "rmse": m["rmse"]}
    return out


def score(pred, T, hz):
    m = calculate_metrics(pred, T["y"], T["valid"], hz)
    m["mean_rmse"], m["mean_mae"] = float(np.nanmean(m["rmse"])), float(np.nanmean(m["mae"]))
    m["acc"] = acc(pred, T["y"], T["clim_t"], T["valid"])
    m["mean_acc"] = float(np.nanmean(m["acc"]))
    return m


@torch.no_grad()
def predict_test(model, data):
    model.eval()
    out = []
    s = data.starts["test"]
    for a in range(0, len(s), 16):
        x, _, _ = data.batch(s[a:a + 16])
        out.append(model(x)[:, :, 0].float().cpu().numpy())
    return np.concatenate(out) * data.sd + data.mu                      # degC


# ----------------------------------------------------------------------------- driver
def estimate_epochs():
    return TC["max_epochs"]


def speed_test(data, device):
    print(f"device {device}; train windows {len(data.starts['train'])}, val {len(data.starts['val'])}, batch {TC['batch_size']}")
    models = build_all(BCFG["models"]["param_budget"], data.H, data.W, data.L, data.C, len(data.hz))
    rows = {}
    for name, m in models.items():
        _, h = fit(m, data, 0, device, max_epochs=1, log=lambda *_: None)
        rows[name] = {"params": n_params(m), "epoch_seconds": h["train_seconds"]}
        print(f"  {name:<16} params {rows[name]['params']:>8,}   1 epoch (train+val) {h['train_seconds']:.1f}s")
    per_seed_max = sum(r["epoch_seconds"] for r in rows.values()) * TC["max_epochs"]
    total_worst = per_seed_max * len(TC["seeds"])
    print(f"worst case ({TC['max_epochs']} epochs, no early stop, {len(TC['seeds'])} seeds, 3 models): {total_worst / 60:.1f} min;  "
          f"with early stopping (typically ~60% of the epochs): ~{0.6 * total_worst / 60:.1f} min")
    (OUT / "speed_test.json").write_text(json.dumps({"device": str(device), "batch_size": TC["batch_size"], "rows": rows,
                                                      "worst_case_minutes": total_worst / 60}, indent=2))


def full_run(data, device):
    (OUT / "runs").mkdir(exist_ok=True)
    T = truth_and_masks(data, "test")
    hz = data.hz.tolist()
    pp = np.repeat(T["last"][:, None], len(hz), 1)
    base = {"persistence": score(pp, T, hz), "climatology": score(T["clim_t"], T, hz)}
    base["persistence"]["seasonal"], base["climatology"]["seasonal"] = seasonal(pp, T, data, hz), seasonal(T["clim_t"], T, data, hz)
    base["climatology"]["acc"] = [None] * len(hz); base["climatology"]["mean_acc"] = None     # forecast anomaly is 0 by construction
    runs = {}
    for seed in TC["seeds"]:
        for name in ("cnn_only", "lstm_only", "hybrid_convlstm"):
            f = OUT / "runs" / f"{name}_seed{seed}.json"
            if f.exists():
                runs[(name, seed)] = json.loads(f.read_text())
                print(f"[skip] {name} seed {seed} (done)")
                continue
            model = build_all(BCFG["models"]["param_budget"], data.H, data.W, data.L, data.C, len(hz))[name]
            print(f"[train] {name} seed {seed}  params {n_params(model):,}")
            model, h = fit(model, data, seed, device)
            pred = predict_test(model, data)
            sc = score(pred, T, hz)
            sc["seasonal"] = seasonal(pred, T, data, hz)
            rec = {"model": name, "seed": seed, "params": n_params(model), "device": str(device), **{k: h[k] for k in
                   ("best_val_loss", "best_epoch", "epochs_run", "train_seconds")}, "history": {k: h[k] for k in ("train_loss", "val_loss")}, "test": sc}
            f.write_text(json.dumps(rec, indent=1))
            np.save(OUT / "runs" / f"{name}_seed{seed}_test_pred.npy", pred.astype("float16"))
            runs[(name, seed)] = rec
            print(f"  -> test RMSE {sc['mean_rmse']:.4f}  MAE {sc['mean_mae']:.4f}  ACC {sc['mean_acc']:.4f}  ({h['train_seconds']:.0f}s, best epoch {h['best_epoch']})")
    return runs, base, T


def summarise(runs, base, data):
    names = ("cnn_only", "lstm_only", "hybrid_convlstm")
    S = {}
    for n in names:
        rs = [runs[(n, s)] for s in TC["seeds"]]

        def ms(get):
            a = np.array([get(r) for r in rs], dtype="float64")
            return {"mean": a.mean(0).tolist(), "std": (a.std(0, ddof=1) if len(a) > 1 else np.zeros_like(a[0])).tolist()}
        S[n] = {"params": rs[0]["params"], "seeds": TC["seeds"],
                "rmse_by_horizon": ms(lambda r: r["test"]["rmse"]), "mae_by_horizon": ms(lambda r: r["test"]["mae"]),
                "acc_by_horizon": ms(lambda r: r["test"]["acc"]),
                "mean_rmse": ms(lambda r: r["test"]["mean_rmse"]), "mean_mae": ms(lambda r: r["test"]["mean_mae"]),
                "mean_acc": ms(lambda r: r["test"]["mean_acc"]),
                "train_seconds": ms(lambda r: r["train_seconds"]), "epochs_run": ms(lambda r: r["epochs_run"]),
                "best_val_loss": ms(lambda r: r["best_val_loss"]),
                "per_seed_mean_rmse": [r["test"]["mean_rmse"] for r in rs], "per_seed_mean_mae": [r["test"]["mean_mae"] for r in rs]}
    for n in names:                                                                        # per-season mean +- sd over seeds
        rs = [runs[(n, sd)] for sd in TC["seeds"]]
        S[n]["seasonal"] = {}
        for season in rs[0]["test"].get("seasonal", {}):
            S[n]["seasonal"][season] = {"n_windows": rs[0]["test"]["seasonal"][season]["n_windows"]}
            for k in ("mean_rmse", "mean_mae", "mean_acc"):
                a_ = np.array([r["test"]["seasonal"][season][k] for r in rs], dtype="float64")
                S[n]["seasonal"][season][k] = {"mean": float(a_.mean()), "std": float(a_.std(ddof=1)) if len(a_) > 1 else 0.0}
    # paired, seed-by-seed comparison: difference = other - hybrid, so POSITIVE means the hybrid is better
    paired = {}
    for other in ("cnn_only", "lstm_only"):
        paired[other] = {}
        for key in ("mean_rmse", "mean_mae"):
            d_ = np.array([runs[(other, sd)]["test"][key] - runs[("hybrid_convlstm", sd)]["test"][key] for sd in TC["seeds"]])
            paired[other][key] = {"per_seed_diff": d_.tolist(), "mean_diff": float(d_.mean()), "sd_diff": float(d_.std(ddof=1)),
                                  "hybrid_better_in_n_seeds": int((d_ > 0).sum()), "n_seeds": len(d_)}
        paired[other]["by_season_mean_rmse_diff"] = {
            sn: {"per_seed_diff": [runs[(other, sd)]["test"]["seasonal"][sn]["mean_rmse"] - runs[("hybrid_convlstm", sd)]["test"]["seasonal"][sn]["mean_rmse"] for sd in TC["seeds"]]}
            for sn in runs[("hybrid_convlstm", TC["seeds"][0])]["test"].get("seasonal", {})}
        for sn, v in paired[other]["by_season_mean_rmse_diff"].items():
            a_ = np.array(v["per_seed_diff"]); v.update(mean_diff=float(a_.mean()), hybrid_better_in_n_seeds=int((a_ > 0).sum()))
    res = {"settings": {"data": data.meta, "training": TC, "models": BCFG["models"], "device": runs[(names[0], TC["seeds"][0])]["device"],
                        "std_note": "std = sample standard deviation (ddof=1) across the 3 seeds"},
           "baselines": base, "models": S, "paired_hybrid_vs": paired, "horizons": data.hz.tolist(), "n_test_windows": int(len(data.starts["test"]))}
    (OUT / "results.json").write_text(json.dumps(res, indent=1, default=float))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--speed-test", action="store_true")
    ap.add_argument("--device", default=None)
    ap.add_argument("--summarise-only", action="store_true")
    a = ap.parse_args()
    device = pick_device(a.device)
    data = Data(device)
    if a.speed_test:
        speed_test(data, device)
        return
    runs, base, _ = full_run(data, device)
    res = summarise(runs, base, data)
    print("\nMean test RMSE / MAE / ACC (mean over horizons; mean +- std over seeds):")
    for n, s in res["models"].items():
        print(f"  {n:<16} RMSE {s['mean_rmse']['mean']:.4f}+-{s['mean_rmse']['std']:.4f}  MAE {s['mean_mae']['mean']:.4f}+-{s['mean_mae']['std']:.4f}  "
              f"ACC {s['mean_acc']['mean']:.4f}+-{s['mean_acc']['std']:.4f}")
    for n, s in res["baselines"].items():
        print(f"  {n:<16} RMSE {s['mean_rmse']:.4f}  MAE {s['mean_mae']:.4f}")


if __name__ == "__main__":
    main()
