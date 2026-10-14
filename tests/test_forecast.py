"""Forecast baselines / metrics on tiny synthetic arrays."""
import json

import numpy as np
import pandas as pd
import pytest

from oceanmind_forecast import (calculate_metrics, climatology_forecast, evaluate_baselines, evaluate_predictions,
                                persistence_forecast)


def test_persistence_shape_and_value():
    x = np.random.default_rng(0).normal(size=(4, 7, 3, 5))          # (N, T, H, W) input windows
    p = persistence_forecast(x[:, -1], 7)
    assert p.shape == (4, 7, 3, 5)
    for h in range(7):
        np.testing.assert_array_equal(p[:, h], x[:, -1])


def test_climatology_selects_day_of_year():
    clim = np.arange(1, 367, dtype="float32")[:, None, None] * np.ones((366, 2, 2), "float32")
    dates = np.array([["2025-01-01", "2025-03-01"], ["2024-12-31", "2024-02-29"]], dtype="datetime64[ns]")
    out = climatology_forecast(clim, dates)
    assert out.shape == (2, 2, 2, 2)
    assert out[0, 0, 0, 0] == 1 and out[0, 1, 0, 0] == 60          # 2025 is not a leap year
    assert out[1, 0, 0, 0] == 366 and out[1, 1, 0, 0] == 60        # 2024 leap day 60 / Dec 31 = 366


def test_mae_rmse_r2_values():
    t = np.array([[[[1.0, 2.0], [3.0, 4.0]]]])                      # (1,1,2,2)
    p = t + np.array([[[[1.0, -1.0], [1.0, -1.0]]]])
    m = calculate_metrics(p, t)
    assert m["mae"][0] == pytest.approx(1.0)
    assert m["rmse"][0] == pytest.approx(1.0)
    assert m["r2"][0] == pytest.approx(1 - 4 / 5.0)                 # SS_res=4, SS_tot=5
    assert calculate_metrics(t, t)["r2"][0] == pytest.approx(1.0)


def test_nan_and_land_excluded():
    t = np.zeros((2, 1, 2, 2))
    p = np.zeros((2, 1, 2, 2))
    p[0, 0, 0, 0] = 100.0                                            # land cell with garbage
    p[0, 0, 0, 1] = np.nan
    t[1, 0, 1, 1] = np.nan
    valid = np.ones_like(t, bool)
    valid[0, 0, 0, 0] = False
    m = calculate_metrics(p, t, valid)
    assert m["mae"][0] == 0.0 and m["rmse"][0] == 0.0
    assert m["n"][0] == 8 - 3


def test_horizons_stay_separate():
    t = np.zeros((3, 3, 2, 2))
    p = np.stack([np.full((3, 2, 2), e) for e in (1.0, 2.0, 3.0)], axis=1)
    m = calculate_metrics(p, t, horizons=[1, 2, 3])
    assert m["mae"] == pytest.approx([1.0, 2.0, 3.0])
    assert m["horizons"] == [1, 2, 3]
    em = evaluate_predictions(p, t, None)
    assert em["mean_mae"] == pytest.approx(2.0)


def _write_processed(root, test_shift=0.0):
    """Minimal processed/ tree: 20 test days on a 2x3 grid, 3-day lookback, horizons 1-2."""
    (root / "cubes").mkdir(parents=True)
    (root / "forecast").mkdir()
    dates = pd.date_range("2025-01-01", periods=20)
    H, W, mu, sd = 2, 3, 10.0, 2.0
    sst = 12.0 + np.arange(20)[:, None, None] * 0.1 + test_shift + np.zeros((20, H, W))
    cube = np.zeros((20, 2, H, W), "float32")
    cube[:, 0] = (sst - mu) / sd
    cube[:, 1] = 1
    np.save(root / "cubes" / "test.npy", cube)
    np.save(root / "cubes" / "test_dates.npy", dates.to_numpy())
    np.save(root / "land_mask.npy", np.zeros((H, W), bool))
    pd.DataFrame({"start_idx": np.arange(15)}).to_parquet(root / "forecast" / "windows_test.parquet")
    (root / "meta.json").write_text(json.dumps({"channels": ["sst", "mask_sst"], "lookback_days": 3,
                                                "horizons": [1, 2], "target_channel": "sst"}))
    (root / "stats.json").write_text(json.dumps({"channels": {"sst": {"mean": mu, "std": sd}}}))
    import xarray as xr
    xr.Dataset({"sst": (("dayofyear", "lat", "lon"), np.full((366, H, W), 11.0, "float32"))},
               coords={"dayofyear": np.arange(1, 367), "lat": [0, 1], "lon": [0, 1, 2]}).to_zarr(root / "climatology.zarr")
    return sst


def test_evaluate_baselines_end_to_end(tmp_path):
    sst = _write_processed(tmp_path)
    res = evaluate_baselines(tmp_path)
    p, c = res["baselines"]["persistence"], res["baselines"]["climatology"]
    assert res["n_windows"] == 15 and res["horizons"] == [1, 2]
    assert p["mae"][0] == pytest.approx(0.1, abs=1e-5) and p["mae"][1] == pytest.approx(0.2, abs=1e-5)
    # climatology is the constant 11.0; truth is sst[window_end + h]
    t = np.array([[sst[s + 2 + h, 0, 0] for h in (1, 2)] for s in range(15)])
    assert c["mae"][0] == pytest.approx(np.abs(t[:, 0] - 11.0).mean(), abs=1e-4)
    assert c["mae_skill_vs_persistence"][0] < 0


def test_no_test_data_used_for_fitting(tmp_path):
    """Shifting every test SST value must not change climatology predictions, only its error."""
    from oceanmind_forecast.evaluate import load_climatology
    _write_processed(tmp_path / "a", 0.0)
    _write_processed(tmp_path / "b", 5.0)
    np.testing.assert_array_equal(load_climatology(tmp_path / "a"), load_climatology(tmp_path / "b"))
    ra = evaluate_baselines(tmp_path / "a")["baselines"]
    rb = evaluate_baselines(tmp_path / "b")["baselines"]
    assert rb["persistence"]["mae"][0] == pytest.approx(ra["persistence"]["mae"][0], abs=1e-4)   # shift-invariant
    assert rb["climatology"]["mae"][0] == pytest.approx(ra["climatology"]["mae"][0] + 5.0, abs=0.2)
