from __future__ import annotations

import argparse
import logging
import json
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oceanmind_model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    x = sub.add_parser("export-dashboard", help="write the forecast snapshot served by the dashboard backend")
    x.add_argument("--config", default="config.yaml")
    x.add_argument("--device", default=None)
    x.add_argument("--out-subdir", default="model")
    hw = sub.add_parser("heatwaves", help="build the marine-heatwave results for one processed dataset (no model, no forecast)")
    hw.add_argument("--config", default="config.yaml")
    hw.add_argument("--dataset-id", default="ne_pacific", help="label stored with the results, e.g. pacific")
    hw.add_argument("--id-prefix", default=None, help="event id prefix (default: mhw, or mhw-<dataset> for datasets other than ne_pacific)")
    hw.add_argument("--out-subdir", default="model")
    ex = sub.add_parser("explain", help="sensitivity of the latest forecast at one place (JSON on stdout)")
    ex.add_argument("--config", default="config.yaml")
    ex.add_argument("--lat", type=float, required=True)
    ex.add_argument("--lon", type=float, required=True)
    ex.add_argument("--device", default=None)
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
    if args.cmd == "export-dashboard":
        from .export_demo import export_dashboard_snapshot
        info = export_dashboard_snapshot(cfg, "best", "test", args.out_subdir, args.device)
        print(f"wrote dashboard snapshot: input ends {info['input_end_date']}, targets {info['target_dates'][0]}..{info['target_dates'][-1]}")
        return 0
    if args.cmd == "explain":
        from .explain import explain_cell
        sys.stdout.write(json.dumps(explain_cell(cfg, args.lat, args.lon, args.device)))
        return 0
    if args.cmd == "heatwaves":
        from .heatwaves import compute_heatwaves
        prefix = args.id_prefix or ("mhw" if args.dataset_id == "ne_pacific" else f"mhw-{args.dataset_id}")
        info = compute_heatwaves(cfg.paths.out_dir, None, args.out_subdir, args.dataset_id, prefix)
        print(f"{args.dataset_id}: latest {info['latest_date']}, {len(info['events'])} active events, active area {info['active_area_km2']:,.0f} km2, "
              f"built in {info['build']['seconds']} s")
        return 0
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
