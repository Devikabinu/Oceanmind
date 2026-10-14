import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_preprocess import features
from oceanmind_preprocess.align import _daily, land_mask_from, regrid
from oceanmind_preprocess.config import load_config
from oceanmind_preprocess.missing import compute_limits, fill_segments, fill_short_gaps
from oceanmind_preprocess.splits import resolve_splits

from conftest import ROOT, make_cfg


def test_config_loads_and_has_all_sections():
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.forecast.lookback_days == 7 and cfg.raw.variables.sst["var"] == "sst"


def test_fill_short_gaps():
    a = np.arange(20, dtype="float32").reshape(20, 1, 1).copy()
    a[3:6] = np.nan      # 3-day gap: filled
    a[8:12] = np.nan     # 4-day gap: left
    a[:2] = np.nan       # leading gap: left
    a[-2:] = np.nan      # trailing gap: left
    out, filled = fill_short_gaps(a, 3)
    assert np.allclose(out[3:6, 0, 0], [3, 4, 5])
    assert np.isnan(out[8:12]).all() and np.isnan(out[:2]).all() and np.isnan(out[-2:]).all()
    assert filled[3:6].all() and filled.sum() == 3


def test_fill_segments_does_not_borrow_across_boundary():
    a = np.arange(10, dtype="float32").reshape(10, 1, 1).copy()
    a[4:6] = np.nan
    out, _ = fill_segments(a, [slice(0, 5), slice(5, 10)], 3)
    assert np.isnan(out[4]).all() and np.isnan(out[5]).all()


def test_clip_limits_use_only_given_data_and_ocean():
    a = np.random.default_rng(0).normal(size=(500, 3, 3)).astype("float32")
    a[:, 0, 0] = 1000  # land-ish cell excluded by the ocean mask
    ocean = np.ones((3, 3), bool)
    ocean[0, 0] = False
    lo, hi = compute_limits(a, ocean, [0.1, 99.9])
    assert hi < 10 and lo > -10


def test_daily_floors_to_utc_midnight_and_averages():
    t = pd.to_datetime(["2020-01-01 06:00", "2020-01-01 18:00", "2020-01-03 12:00"])
    da = xr.DataArray([1.0, 3.0, 5.0], dims="time", coords={"time": t})
    d = _daily(da)
    assert list(d.time.dt.hour.values) == [0, 0, 0] and d.values[0] == 2.0 and np.isnan(d.values[1])


def test_regrid_bilinear_is_nan_aware_and_keeps_land():
    lat, lon = np.arange(0, 3.1, 1.0), np.arange(0, 3.1, 1.0)
    v = np.tile(np.arange(4.0), (4, 1)).astype("float32")[None]  # value = lon
    v[:, 0, 0] = np.nan
    da = xr.DataArray(v, dims=("time", "lat", "lon"), coords={"time": [0], "lat": lat, "lon": lon})
    out = regrid(da, np.arange(0, 3.01, 0.5), np.arange(0, 3.01, 0.5))
    assert np.allclose(out.values[0, 2:, 2:], np.tile(np.arange(1.0, 3.01, 0.5), (5, 1)), atol=1e-5)
    assert np.isfinite(out.values[0, 1, 1])      # coast cell not eroded to NaN
    da2 = da.copy()
    da2[:, :2, :2] = np.nan
    assert np.isnan(regrid(da2, np.arange(0, 3.01, 0.5), np.arange(0, 3.01, 0.5)).values[0, 0, 0])


def test_land_mask_is_always_nan_cells():
    a = np.random.default_rng(0).random((10, 3, 3)).astype("float32")
    a[:, 1, 1] = np.nan
    a[3, 0, 0] = np.nan
    m = land_mask_from(a)
    assert m[1, 1] and m.sum() == 1


def test_climatology_is_periodic_and_smooth():
    times = pd.date_range("2018-01-01", "2020-12-31")
    a = (10 + 3 * np.sin(2 * np.pi * (times.dayofyear.values - 1) / 365.25))[:, None, None].astype("float32") * np.ones((1, 2, 2), "float32")
    raw, sm = features.daily_climatology(a, times, 7.0)
    assert sm.shape == (366, 2, 2) and np.isfinite(sm).all()
    assert abs(sm[0, 0, 0] - sm[-1, 0, 0]) < 0.2    # wraps around the year end
    assert np.allclose(features.anomaly(a, sm, times).mean(), 0, atol=0.1)


def test_gradient_of_linear_field():
    lat = np.array([10.0, 10.25, 10.5])
    lon = np.arange(5) * 0.25
    a = np.broadcast_to((2.0 * lon)[None, None, :], (1, 3, 5)).astype("float32").copy()
    g = features.gradient_magnitude(a, lat, 0.25)
    expect = 2 / (features.KM_PER_DEG * np.cos(np.deg2rad(lat))) * 100
    assert np.allclose(g[0, :, 2], expect, rtol=1e-3)


def test_rolling_and_lag():
    a = np.arange(10, dtype="float32").reshape(10, 1, 1)
    m, s = features.rolling_stats(a, 3, 3)
    assert np.isnan(m[1, 0, 0]) and m[5, 0, 0] == 4.0 and np.isclose(s[5, 0, 0], np.std([3, 4, 5]))
    assert features.lag(a, 2)[5, 0, 0] == 3 and np.isnan(features.lag(a, 2)[1, 0, 0])


def test_splits_sizes_and_overlap_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    times = pd.date_range("2019-01-01", "2021-05-31")
    sp = resolve_splits(cfg, times)
    assert sp["train"].n + sp["val"].n + sp["test"].n == len(times)
    assert sp["test"].end == times[-1]            # null end = latest available
    cfg.splits.val = ["2020-12-01", "2021-03-31"]
    with pytest.raises(ValueError, match="overlaps"):
        resolve_splits(cfg, times)
