from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np

DESC = {
    "persistence": "the SST map of the last day in the 7-day input window is repeated as the forecast for horizons 1-7 days.",
    "climatology": "the TRAIN-only (2012-2023) smoothed daily climatology from `processed/climatology.zarr` is looked up "
                   "by the target date's day-of-year; it ignores the input window.",
}


def save_metrics(res, d):
    d.mkdir(parents=True, exist_ok=True)
    (d / "baseline_metrics.json").write_text(json.dumps(res, indent=2))
    with open(d / "baseline_metrics.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["baseline", "horizon_days", "mae_degC", "rmse_degC", "r2", "mae_skill_vs_persistence",
                    "rmse_skill_vs_persistence", "n_cells"])
        for n, r in res["baselines"].items():
            for i, h in enumerate(res["horizons"]):
                w.writerow([n, h, r["mae"][i], r["rmse"][i], r["r2"][i], r["mae_skill_vs_persistence"][i],
                            r["rmse_skill_vs_persistence"][i], r["n"][i]])
            w.writerow([n, "mean", r["mean_mae"], r["mean_rmse"], r["mean_r2"], "", "", ""])


def plots(res, d):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d.mkdir(parents=True, exist_ok=True)
    hz, B = res["horizons"], res["baselines"]
    col = {"persistence": "#1f77b4", "climatology": "#d95f02"}
    for key, lab, fn in (("mae", "MAE (°C)", "mae_vs_horizon"), ("rmse", "RMSE (°C)", "rmse_vs_horizon"),
                         ("r2", "R²", "r2_vs_horizon")):
        fig, ax = plt.subplots(figsize=(6, 4))
        for n, r in B.items():
            ax.plot(hz, r[key], "o-", label=n, color=col[n])
        ax.set(xlabel="Forecast horizon (days)", ylabel=lab,
               title=f"{lab} vs horizon, test {res['date_range'][0]} to {res['date_range'][1]}")
        ax.grid(alpha=.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(d / f"{fn}.png", dpi=150)
        plt.close(fig)
    fig, axs = plt.subplots(1, 3, figsize=(14, 4))
    w = 0.38
    x = np.arange(len(hz))
    for ax, (key, lab) in zip(axs, (("mae", "MAE (°C)"), ("rmse", "RMSE (°C)"), ("r2", "R²"))):
        for j, (n, r) in enumerate(B.items()):
            ax.bar(x + (j - .5) * w, r[key], w, label=n, color=col[n])
        ax.set_xticks(x, hz)
        ax.set(xlabel="Horizon (days)", ylabel=lab, title=lab)
        ax.grid(alpha=.3, axis="y")
    axs[0].legend()
    fig.suptitle("Persistence vs climatology (test split)")
    fig.tight_layout()
    fig.savefig(d / "persistence_vs_climatology.png", dpi=150)
    plt.close(fig)


def write_report(res, path):
    B, hz = res["baselines"], res["horizons"]
    L = ["# OceanMind baseline forecast report", "",
         f"- Split: **{res['split']}**, {res['date_range'][0]} to {res['date_range'][1]}; {res['n_windows']} forecast windows "
         f"(7-day lookback, horizons {hz[0]}-{hz[-1]} days); grid 120x160 at 0.25°.",
         "- Metrics are in °C over valid ocean cells only (observed/gap-filled on both the forecast-origin and target day, "
         f"so both baselines are scored on identical cells; {res['n_valid_cells']:,} cell-forecasts).",
         "- R² is pooled over all valid cells and windows of a horizon, relative to the mean target SST of that horizon "
         "(so it includes the seasonal and spatial variance).",
         "- No test data was used for fitting: climatology, normalisation constants and clipping limits are TRAIN-only.", ""]
    for n in B:
        L += [f"## {n.capitalize()} baseline", "", f"For each window, {DESC[n]}", ""]
    L += ["## Metrics per horizon", ""]
    for n, r in B.items():
        L += [f"### {n}", "", "| Horizon | MAE (°C) | RMSE (°C) | R² | MAE skill vs persistence | RMSE skill vs persistence |",
              "|---|---|---|---|---|---|"]
        for i, h in enumerate(hz):
            L.append(f"| {h}-day | {r['mae'][i]:.4f} | {r['rmse'][i]:.4f} | {r['r2'][i]:.4f} | "
                     f"{r['mae_skill_vs_persistence'][i]:+.3f} | {r['rmse_skill_vs_persistence'][i]:+.3f} |")
        L += [f"| **mean** | {r['mean_mae']:.4f} | {r['mean_rmse']:.4f} | {r['mean_r2']:.4f} | | |", ""]
    p, c = B["persistence"], B["climatology"]
    L += ["## Persistence vs climatology", "", "| Horizon | MAE pers | MAE clim | RMSE pers | RMSE clim | better (MAE) |",
          "|---|---|---|---|---|---|"]
    for i, h in enumerate(hz):
        L.append(f"| {h}-day | {p['mae'][i]:.4f} | {c['mae'][i]:.4f} | {p['rmse'][i]:.4f} | {c['rmse'][i]:.4f} | "
                 f"{'persistence' if p['mae'][i] < c['mae'][i] else 'climatology'} |")
    wins = [h for i, h in enumerate(hz) if p["mae"][i] < c["mae"][i]]
    L += ["", "## Conclusions", ""]
    if len(wins) == len(hz):
        L.append(f"- Persistence has lower MAE than climatology at every horizon (mean MAE {p['mean_mae']:.3f} vs {c['mean_mae']:.3f} °C).")
    elif not wins:
        L.append(f"- Climatology has lower MAE than persistence at every horizon (mean MAE {c['mean_mae']:.3f} vs {p['mean_mae']:.3f} °C).")
    else:
        L.append(f"- Persistence wins on MAE at horizons {wins}; climatology wins elsewhere "
                 f"(mean MAE {p['mean_mae']:.3f} vs {c['mean_mae']:.3f} °C).")
    stronger = "persistence" if p["mean_mae"] < c["mean_mae"] else "climatology"
    agree = (p["mean_mae"] < c["mean_mae"]) == (p["mean_rmse"] < c["mean_rmse"])
    L += [f"- Stronger overall baseline by mean MAE: **{stronger}** "
          f"({'mean RMSE agrees' if agree else 'mean RMSE disagrees'}).",
          "- Persistence error grows with lead time while climatology error is horizon-independent, so a learned model "
          "should be judged against the better of the two at each horizon.", ""]
    Path(path).write_text("\n".join(L), encoding="utf-8")
