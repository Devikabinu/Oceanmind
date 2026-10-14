from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oceanmind_forecast")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("evaluate", help="evaluate persistence and climatology baselines on the test split")
    e.add_argument("--config", default="config.yaml")
    e.add_argument("--split", default="test")
    e.add_argument("--no-predictions", action="store_true", help="do not save baseline prediction arrays")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)

    from oceanmind_preprocess.config import load_config
    from .evaluate import evaluate_baselines
    from .report import plots, save_metrics, write_report

    cfg = load_config(args.config)
    out = Path(cfg.paths.out_dir)
    res, preds, d = evaluate_baselines(out, args.split, return_predictions=True)
    bdir = out / "forecast" / "baselines"
    save_metrics(res, bdir)
    plots(res, out / "figures" / "forecast")
    write_report(res, bdir / "baseline_report.md")
    if not args.no_predictions:
        pdir = bdir / "baseline_predictions"
        pdir.mkdir(exist_ok=True)
        for n, p in preds.items():
            np.save(pdir / f"{n}_{args.split}.npy", p.astype("float32"))
        np.save(pdir / f"target_dates_{args.split}.npy", d["target_dates"])
    for n, r in res["baselines"].items():
        print(f"\n{n}  (mean MAE {r['mean_mae']:.4f}  RMSE {r['mean_rmse']:.4f}  R2 {r['mean_r2']:.4f})")
        for i, h in enumerate(res["horizons"]):
            print(f"  {h}d  MAE {r['mae'][i]:.4f}  RMSE {r['rmse'][i]:.4f}  R2 {r['r2'][i]:.4f}")
    print(f"\nsaved to {bdir} and {out / 'figures' / 'forecast'}")
    return 0
