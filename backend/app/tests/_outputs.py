"""Builds a tiny, hand-made ML-export directory (TEST DATA ONLY) so the dashboard endpoints can be tested without the
real processed/ files. A 16x16 grid: land strip on the west edge, one warm block (rows/cols 0-7) that is a marine
heatwave, everything else +1.0 degC above climatology."""
import json

import numpy as np

H = W = 16
N = 7
OBS_DATE = "2026-09-27"
TARGETS = [f"2026-09-{28 + i}" if 28 + i <= 30 else f"2026-10-{28 + i - 30:02d}" for i in range(N)]
LAT0, LON0 = 20.125, -159.875


def build(tmp_path, with_heatwave=True, with_history=True):
    dash = tmp_path / "model" / "dashboard"
    dash.mkdir(parents=True)
    lat = (LAT0 + 0.25 * np.arange(H)).astype("float32")
    lon = (LON0 + 0.25 * np.arange(W)).astype("float32")
    ocean = np.ones((H, W), bool)
    ocean[:, :2] = False
    land = np.where(ocean, 0.0, np.nan).astype("float32")
    base = (15 + land).astype("float32")
    clim = np.broadcast_to(base - 1.0, (N, H, W)).copy()
    fc = np.broadcast_to(base, (N, H, W)).copy()
    obs = base.copy()
    obs[:8, :8] += 3.0
    fcl = np.broadcast_to(obs + 0.5, (N, H, W)).copy()
    snap = dict(
        lat=lat, lon=lon, ocean=ocean, forecast=fc, truth=fc + 0.1, climatology=clim, observed_last=base,
        climatology_last=base - 1.0, latest_forecast=fcl, latest_climatology=clim, latest_obs=obs,
        latest_obs_climatology=base - 1.0, daily_mean=np.full(100, 15.0, "float32"), daily_clim=np.full(100, 14.0, "float32"),
        daily_dates=np.asarray(([f"2026-06-{d:02d}" for d in range(1, 31)] * 4)[:100], dtype="U10"),
    )
    np.savez_compressed(dash / "snapshot.npz", **snap)
    (dash / "snapshot.json").write_text(json.dumps({
        "split": "test", "model": "m", "checkpoint": {"which": "best", "epoch": 5, "val_loss": 0.004},
        "input_end_date": "2026-09-20", "horizons": list(range(1, 8)),
        "target_dates": [f"2026-09-{21 + i}" for i in range(7)], "kind": "hindcast", "note": "n",
        "grid": {"n_lat": H, "n_lon": W, "resolution_deg": 0.25},
        "latest": {"observed_date": OBS_DATE, "target_dates": TARGETS, "n_nrt_input_days": 0, "note": "latest"},
    }))
    block = np.zeros((H, W), bool)
    block[:8, 2:8] = True
    if with_heatwave:
        np.savez_compressed(
            dash / "heatwave_state.npz",
            run_len=np.where(block, 10, 0).astype("int16"), active=block,
            cur_anom=np.where(block, 4.0, np.nan).astype("float32"), peak_anom=np.where(block, 4.5, np.nan).astype("float32"),
            category=np.where(block, 2, 0).astype("int8"), percentile=np.where(ocean, 97.0, np.nan).astype("float32"),
            thr_latest=np.full((H, W), 15.5, "float32"), clim_latest=np.full((H, W), 14.0, "float32"),
            fc_above=np.broadcast_to(block, (N, H, W)).copy(),
        )
        ev = {
            "id": f"mhw-{OBS_DATE}-1", "status": "ACTIVE", "start_date": "2026-09-17", "last_observed_date": OBS_DATE,
            "duration_days": 11, "cells": int(block.sum()), "area_km2": 150000.0, "centroid": {"lat": 21.0, "lon": -159.0},
            "bbox": {"lat_min": 20.0, "lat_max": 22.0, "lon_min": -159.5, "lon_max": -158.0},
            "current_anomaly_c": 4.0, "max_anomaly_c": 4.5, "category": 2, "category_name": "II (Strong)",
            "historical_percentile": 97.0, "forecast_still_above_p90_day7": 1.0,
            "cumulative_intensity_c_days": 44.0, "max_cumulative_intensity_c_days": 49.5,
            "timeline": [{"date": f"2026-09-{d:02d}", "area_km2": 10000.0 * (d - 16), "mean_anomaly_c": 1.0 + 0.3 * (d - 17)} for d in range(17, 28)],
        }
        (dash / "heatwave.json").write_text(json.dumps({
            "method": "test method", "baseline": ["2012-01-01", "2023-12-31"], "data_source": "test", "latest_date": OBS_DATE,
            "ocean_area_km2": 1000000.0, "active_area_km2": 150000.0, "active_share": 0.15, "active_area_historical_rank_pct": 90.0,
            "min_event_cells": 10, "events": [ev], "yearly": {"2026": {"days": 270, "max_area_km2": 1.0, "mean_area_km2": 1.0, "days_with_heatwave_area_over_5pct": 3}},
            "daily": {"dates": [f"2026-06-{d:02d}" for d in range(1, 31)], "mean_sst": [15.0] * 30, "mean_anomaly": [1.0] * 30,
                      "heatwave_area_km2": [1000.0 * d for d in range(30)]},
        }))
    if with_history:
        n = 30
        np.savez_compressed(
            dash / "point_history.npz", dates=np.asarray([f"2026-09-{d:02d}" for d in range(1, 31)], dtype="U10"),
            sst_c=np.where(ocean, 1500, -32768).astype("int16")[None].repeat(n, axis=0),
            clim_c=np.full((366, H, W), 1400, "int16"), thr_c=np.full((366, H, W), 1450, "int16"),
        )
    mae = lambda x: [x] * N  # noqa: E731
    stats = lambda m: {"mae": mae(m), "rmse": mae(m), "r2": mae(0.99), "mean_mae": m, "mean_rmse": m, "mean_r2": 0.99}  # noqa: E731
    (tmp_path / "model" / "model_metrics.json").write_text(json.dumps({
        "split": "test", "date_range": ["2025-01-01", "2026-09-27"], "n_windows": 5, "horizons": list(range(1, 8)),
        "baselines": {
            "convlstm": {**stats(0.2), "mae_skill_vs_persistence": mae(0.2), "rmse_skill_vs_persistence": mae(0.2)},
            "persistence": stats(0.25), "climatology": stats(0.6),
        },
    }))
    return tmp_path
