from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oceanmind_model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train", help="train on TRAIN, early-stop on VALIDATION")
    e = sub.add_parser("evaluate", help="score a checkpoint and compare with the baselines")
    for p in (t, e):
        p.add_argument("--config", default="config.yaml")
        p.add_argument("--device", default=None, help="auto | cpu | cuda (default: training.device)")
        p.add_argument("--out-subdir", default="model", help="processed/<subdir> for checkpoints and reports")
    t.add_argument("--epochs", type=int, default=None)
    t.add_argument("--batch-size", type=int, default=None)
    t.add_argument("--limit-train", type=int, default=None, help="use only N evenly spaced train windows (smoke runs)")
    t.add_argument("--limit-val", type=int, default=None)
    e.add_argument("--checkpoint", default="best", choices=["best", "last"])
    e.add_argument("--split", default="test", choices=["val", "test"])
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)

    from oceanmind_preprocess.config import load_config
    cfg = load_config(args.config)
    if args.cmd == "train":
        from .train import train
        train(cfg, args.out_subdir, args.epochs, args.batch_size, args.device, args.limit_train, args.limit_val)
    else:
        from .evaluate import evaluate_model
        res = evaluate_model(cfg, args.checkpoint, args.split, args.out_subdir, args.device)
        hz = res["horizons"]
        print(f"\n{res['split']} {res['date_range']}  windows={res['n_windows']}")
        print("horizon  " + "  ".join(f"{n:>22}" for n in res["baselines"]))
        for i, h in enumerate(hz):
            print(f"{h}d       " + "  ".join(
                f"{r['mae'][i]:.4f}/{r['rmse'][i]:.4f}/{r['r2'][i]:.4f}" for r in res["baselines"].values()))
        print("(MAE/RMSE/R2)")
        for n, r in res["baselines"].items():
            print(f"mean {n}: MAE {r['mean_mae']:.4f} RMSE {r['mean_rmse']:.4f} R2 {r['mean_r2']:.4f}")
    return 0
