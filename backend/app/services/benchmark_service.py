"""Read-only view of one saved model-benchmark run (written by scripts/benchmark/, stored under processed/benchmark/<run>/).

Nothing here trains or computes model results: every number is read unchanged from that run's results.json.
"""
from __future__ import annotations

import base64

from app.services import environment as _environment
from app.services.environment import OutputsUnavailable, read_json  # noqa: F401  (OutputsUnavailable is what the endpoint turns into a 503)

RUN_DIR = "followup_3yr"                      # the saved benchmark run this page presents (3-year block)
MAPS_FILE = "sample_maps.png"                 # the only image served; the file name is fixed here, never taken from a request
LABEL = {"cnn_only": "CNN-only", "lstm_only": "LSTM-only", "hybrid_convlstm": "Hybrid ConvLSTM"}


def run_dir():
    return _environment.processed_dir() / "benchmark" / RUN_DIR


def _model(key: str, m: dict) -> dict:
    return {
        "key": key, "label": LABEL[key], "params": m["params"],
        "mean_rmse": m["mean_rmse"], "mean_mae": m["mean_mae"], "mean_acc": m["mean_acc"],
        "rmse_by_horizon": m["rmse_by_horizon"], "mae_by_horizon": m["mae_by_horizon"],
        "train_seconds": m["train_seconds"]["mean"],
    }


def _baseline(b: dict) -> dict:
    return {"mean_rmse": b["mean_rmse"], "mean_mae": b["mean_mae"], "rmse": b["rmse"], "mae": b["mae"], "mean_acc": b.get("mean_acc")}


def benchmark() -> dict:
    root = run_dir()
    res = read_json(root / "results.json")
    meta = res["settings"]["data"]
    maps = root / MAPS_FILE
    image = ("data:image/png;base64," + base64.b64encode(maps.read_bytes()).decode("ascii")) if maps.exists() else None
    sm = res.get("sample_map") or {}
    return {
        "title": "3-year benchmark",
        "test_period": meta["split_dates"]["test"],
        "horizons": res["horizons"],
        "models": [_model(k, res["models"][k]) for k in ("cnn_only", "lstm_only", "hybrid_convlstm")],
        "baselines": {"persistence": _baseline(res["baselines"]["persistence"]), "climatology": _baseline(res["baselines"]["climatology"])},
        "sample_map": {"image": image, "date": sm.get("date"), "horizon_days": sm.get("horizon_days")},
    }
