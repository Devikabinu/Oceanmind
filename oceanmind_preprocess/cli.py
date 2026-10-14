from __future__ import annotations

import argparse
import logging
import sys

import numpy as np


def main(argv=None):
    ap = argparse.ArgumentParser(prog="oceanmind_preprocess")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build all model-ready datasets")
    b.add_argument("--config", default="config.yaml")
    l = sub.add_parser("latest", help="build the most recent model input window")
    l.add_argument("--config", default="config.yaml")
    l.add_argument("--date", default=None, help="last input day (default: latest available)")
    l.add_argument("--out", default=None, help="optional .npz path to save the window")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)

    from .config import load_config
    if args.cmd == "build":
        from .pipeline import build
        build(load_config(args.config))
    else:
        from .inference import build_latest_window
        w = build_latest_window(args.date, args.config)
        print(f"as_of={w['as_of']} x={w['x'].shape} nrt_days={w['n_nrt_days']}/{len(w['dates'])} flags={w['nrt_flags']}")
        if args.out:
            np.savez_compressed(args.out, x=w["x"], dates=w["dates"], nrt_flags=w["nrt_flags"], ocean=w["ocean"],
                                channels=w["channels"], n_nrt_days=w["n_nrt_days"])
    return 0
