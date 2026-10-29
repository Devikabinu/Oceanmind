"""Figures and the results table from processed/benchmark/results.json (+ saved test predictions). Reads results only; trains nothing.

    python scripts/benchmark/make_report.py

Sample maps use a rule fixed in advance (not chosen after looking at results): seed 0, the MIDDLE test window, horizon 7 days.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
OUT = ROOT / "processed" / "benchmark" / os.environ.get("BENCH_SUBDIR", "")
LABEL = {"cnn_only": "CNN-only", "lstm_only": "LSTM-only", "hybrid_convlstm": "Hybrid ConvLSTM"}
COLOR = {"cnn_only": "#1f77b4", "lstm_only": "#d62728", "hybrid_convlstm": "#2ca02c"}


def error_vs_horizon(res):
    hz = res["horizons"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, key, title in ((axes[0], "rmse", "RMSE (degC)"), (axes[1], "mae", "MAE (degC)")):
        for n, m in res["models"].items():
            mu, sd = np.array(m[f"{key}_by_horizon"]["mean"]), np.array(m[f"{key}_by_horizon"]["std"])
            ax.plot(hz, mu, "o-", color=COLOR[n], label=f"{LABEL[n]} ({m['params']:,} params)")
            ax.fill_between(hz, mu - sd, mu + sd, color=COLOR[n], alpha=0.18)
        for n, ls in (("persistence", "k--"), ("climatology", "k:")):
            ax.plot(hz, res["baselines"][n][key], ls, label=n.capitalize())
        ax.set(xlabel="Forecast horizon (days)", ylabel=title, title=f"Test {title.split()[0]} vs horizon")
        ax.grid(alpha=.3)
    axes[0].legend(fontsize=8)
    s = res["settings"]["data"]
    fig.suptitle(f"Test block {s['split_dates']['test'][0]} .. {s['split_dates']['test'][1]}; mean +- sd over {len(res['models']['hybrid_convlstm']['seeds'])} seeds "
                 "(shaded)", fontsize=9)
    fig.tight_layout()
    fig.savefig(OUT / "error_vs_horizon.png", dpi=150)
    plt.close(fig)


def sample_maps(res):
    from run_benchmark import Data, truth_and_masks
    data = Data(__import__("torch").device("cpu"))
    T = truth_and_masks(data, "test")
    w = len(T["starts"]) // 2                                        # middle test window
    h = data.hz.tolist().index(7)
    truth, persist = T["y"][w, h], T["last"][w]
    date = data.times[T["tgt"][w, h]].date()
    preds = {n: np.load(OUT / "runs" / f"{n}_seed0_test_pred.npy").astype("float32")[w, h] for n in res["models"]}
    extent = [data.lon[0], data.lon[-1], data.lat[0], data.lat[-1]]
    vmin, vmax = np.nanmin(truth) - 0.3, np.nanmax(truth) + 0.3
    emax = max(np.nanmax(np.abs(p - truth)) for p in list(preds.values()) + [persist])
    cols = ["Truth (observed)", "Persistence", *[LABEL[n] for n in preds]]
    fields = [truth, persist, *preds.values()]
    fig, axes = plt.subplots(2, len(cols), figsize=(3.3 * len(cols), 6.2))
    for j, (c, f) in enumerate(zip(cols, fields)):
        im = axes[0, j].imshow(f, origin="lower", extent=extent, vmin=vmin, vmax=vmax, cmap="turbo", aspect="auto")
        axes[0, j].set_title(c, fontsize=10)
        if j == 0:
            axes[1, j].axis("off")
        else:
            er = axes[1, j].imshow(f - truth, origin="lower", extent=extent, vmin=-emax, vmax=emax, cmap="RdBu_r", aspect="auto")
            rm = float(np.sqrt(np.nanmean((f - truth) ** 2)))
            axes[1, j].set_title(f"error (forecast - truth), RMSE {rm:.2f}", fontsize=8)
    fig.colorbar(im, ax=axes[0, :].tolist(), shrink=0.8, label="SST (degC)")
    fig.colorbar(er, ax=axes[1, 1:].tolist(), shrink=0.8, label="error (degC)")
    fig.suptitle(f"7-day forecast for {date} (model output; seed 0; middle test window; truth = NOAA OISST)", fontsize=10)
    fig.savefig(OUT / "sample_maps.png", dpi=140, bbox_inches="tight")
    for n, p in preds.items():                                         # one map file per model as well
        f2, ax = plt.subplots(1, 3, figsize=(10, 3.4))
        for a, fld, t in zip(ax, (truth, p, p - truth), ("Truth", LABEL[n] + " forecast", "Error")):
            if t == "Error":
                im2 = a.imshow(fld, origin="lower", extent=extent, vmin=-emax, vmax=emax, cmap="RdBu_r", aspect="auto")
            else:
                im2 = a.imshow(fld, origin="lower", extent=extent, vmin=vmin, vmax=vmax, cmap="turbo", aspect="auto")
            a.set_title(t, fontsize=10)
            f2.colorbar(im2, ax=a, shrink=0.8)
        f2.suptitle(f"{LABEL[n]}: 7-day forecast for {date} (seed 0)", fontsize=10)
        f2.tight_layout()
        f2.savefig(OUT / f"sample_map_{n}.png", dpi=140)
        plt.close(f2)
    plt.close(fig)
    return {"date": str(date), "window_index": int(w), "horizon_days": 7, "seed": 0}


def table(res):
    pm = lambda d, k=4: f"{d['mean']:.{k}f} +- {d['std']:.{k}f}"
    L = ["| Model | Params | Mean RMSE (degC) | Mean MAE (degC) | Mean ACC | Train time (s) | Epochs |", "|---|---|---|---|---|---|---|"]
    for n, m in res["models"].items():
        L.append(f"| {LABEL[n]} | {m['params']:,} | {pm(m['mean_rmse'])} | {pm(m['mean_mae'])} | {pm(m['mean_acc'])} | "
                 f"{m['train_seconds']['mean']:.0f} +- {m['train_seconds']['std']:.0f} | {m['epochs_run']['mean']:.1f} |")
    for n in ("persistence", "climatology"):
        b = res["baselines"][n]
        acc = "n/a" if b["mean_acc"] is None else f"{b['mean_acc']:.4f}"
        L.append(f"| {n.capitalize()} | 0 | {b['mean_rmse']:.4f} | {b['mean_mae']:.4f} | {acc} | - | - |")
    hz = res["horizons"]
    for key, name in (("rmse", "RMSE"), ("mae", "MAE"), ("acc", "ACC")):
        L += ["", f"**{name} by horizon** (test; mean +- sd over seeds)", "", "| Horizon (d) | " + " | ".join(LABEL[n] for n in res["models"]) + " | Persistence | Climatology |",
              "|---|" + "---|" * (len(res["models"]) + 2)]
        for i, h in enumerate(hz):
            cells = [pm({"mean": m[f"{key}_by_horizon"]["mean"][i], "std": m[f"{key}_by_horizon"]["std"][i]}, 3) for m in res["models"].values()]
            for n in ("persistence", "climatology"):
                v = res["baselines"][n][key][i]
                cells.append("n/a" if v is None else f"{v:.3f}")
            L.append(f"| {h} | " + " | ".join(cells) + " |")
    if res["models"]["hybrid_convlstm"].get("seasonal"):
        seas = list(res["models"]["hybrid_convlstm"]["seasonal"])
        L += ["", "**Mean RMSE (degC) by season of the test year** (mean +- sd over seeds; n = test windows)", "",
              "| Season (n) | " + " | ".join(LABEL[n] for n in res["models"]) + " | Persistence |", "|---|" + "---|" * (len(res["models"]) + 1)]
        for sn in seas:
            n_w = res["models"]["hybrid_convlstm"]["seasonal"][sn]["n_windows"]
            cells = [pm(m["seasonal"][sn]["mean_rmse"], 3) for m in res["models"].values()] + [f"{res['baselines']['persistence']['seasonal'][sn]['mean_rmse']:.3f}"]
            L.append(f"| {sn} ({n_w}) | " + " | ".join(cells) + " |")
    if res.get("paired_hybrid_vs"):
        L += ["", "**Paired comparison, seed by seed** (difference = other model - hybrid, in degC; POSITIVE = hybrid better)", "",
              "| Hybrid vs | Metric | Mean diff | sd of diff | Hybrid better in |", "|---|---|---|---|---|"]
        for other, v in res["paired_hybrid_vs"].items():
            for k in ("mean_rmse", "mean_mae"):
                x = v[k]
                L.append(f"| {LABEL[other]} | {k.replace('mean_', '').upper()} | {x['mean_diff']:+.4f} | {x['sd_diff']:.4f} | {x['hybrid_better_in_n_seeds']} of {x['n_seeds']} seeds |")
            for sn, x in v["by_season_mean_rmse_diff"].items():
                L.append(f"| {LABEL[other]} | RMSE, {sn} only | {x['mean_diff']:+.4f} | - | {x['hybrid_better_in_n_seeds']} of {len(x['per_seed_diff'])} seeds |")
    (OUT / "results_table.md").write_text("\n".join(L) + "\n")
    return "\n".join(L)


if __name__ == "__main__":
    res = json.loads((OUT / "results.json").read_text())
    error_vs_horizon(res)
    info = sample_maps(res)
    res["sample_map"] = info
    (OUT / "results.json").write_text(json.dumps(res, indent=1))
    print(table(res))
    print("sample map:", info)
