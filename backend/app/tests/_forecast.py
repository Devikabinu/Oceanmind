"""Forecast files for the synthetic Pacific grid, in the format `oceanmind_model evaluate` / `export-dashboard` write. Test data only."""
import json

import numpy as np

from app.tests import _pacific as P


def build(root, beats_persistence=False, issued=P.LATEST, slope=0.1):
    d = root / "model"
    (d / "dashboard").mkdir(parents=True, exist_ok=True)
    land = P.land_mask()
    sst, _ = P.raw_fields(19)
    obs = np.where(land, np.nan, sst).astype("float32")
    clim = np.where(land, np.nan, sst - 0.5).astype("float32")
    n = 7
    fc = np.stack([obs + slope * (h + 1) for h in range(n)]).astype("float32")
    climn = np.stack([clim for _ in range(n)]).astype("float32")
    np.savez_compressed(d / "dashboard" / "snapshot.npz", lat=P.LAT.astype("float32"), lon=P.LON.astype("float32"), ocean=~land, latest_forecast=fc,
                        latest_climatology=climn, latest_obs=obs, latest_obs_climatology=clim)
    (d / "dashboard" / "snapshot.json").write_text(json.dumps({
        "model": "ConvLSTM (2 layers, 32 hidden channels)", "checkpoint": {"which": "best", "epoch": 12, "val_loss": 0.1}, "horizons": list(range(1, n + 1)),
        "grid": {"resolution_deg": 4.0}, "latest": {"observed_date": issued, "target_dates": [f"2020-01-{20 + h + 1}" for h in range(n)],
                                                   "note": "Operational-style forecast issued from the last processed day."}}))

    def m(mae):
        return {"mae": [mae] * n, "rmse": [mae * 1.2] * n, "r2": [0.99] * n, "mean_mae": mae, "mean_rmse": mae * 1.2, "mean_r2": 0.99, "n": [100] * n}

    conv = m(0.30 if beats_persistence else 0.40)
    conv["mae_skill_vs_persistence"] = [1 - conv["mae"][0] / 0.35] * n
    (d / "model_metrics.json").write_text(json.dumps({"split": "test", "date_range": ["2020-01-14", "2020-01-20"], "n_windows": 20, "horizons": list(range(1, n + 1)),
                                                      "baselines": {"convlstm": conv, "persistence": m(0.35), "climatology": m(0.55)}}))
    (d / "checkpoint_origin.json").write_text(json.dumps({"origin": "processed/model/best_model.pt", "trained_on": "ne_pacific (NOAA OISST study region)", "retrained": False}))
    return d
