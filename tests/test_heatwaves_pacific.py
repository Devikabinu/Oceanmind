"""Marine-heatwave detection on a synthetic Pacific-like processed dataset (grid crossing 180 degrees, land, missing days). Deterministic, no network.

The dataset is a small processed directory in the same layout the preprocessing pipeline writes; SST is a seasonal cycle plus fixed noise, and heatwaves are
injected as known anomalies in the last days, so every metric has a known expected value."""
import json
import warnings

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_model.heatwaves import CATEGORY_NAMES, _cell_area_km2, compute_heatwaves, detect_runs

LAT = np.arange(-9.5, 10.0, 1.0)                    # 19 rows around the equator, 1 degree cells
LON = np.arange(172.5, 189.0, 1.0)                  # 172.5 .. 188.5 east: crosses 180 inside the array
H, W = len(LAT), len(LON)
DATES = pd.date_range("2012-01-01", "2024-03-31")
MU, SD = 20.0, 5.0
SOURCE = {"provider_id": "temporary_pacific_generated", "provider_type": "generated_temporary", "is_observational": False, "description": "generated (test)"}
LAND = np.zeros((H, W), bool)
LAND[0:3, 0:4] = True                                # a land block in the south-west corner


def clim_curve():
    doy = np.arange(1, 367)
    return (20.0 + 4.0 * np.sin(2 * np.pi * (doy - 80) / 366.0)).astype("float32")


def build(root, events=(), missing=(), source=SOURCE, land_hot=False, noise=0.3):
    """events: (rows, cols, n_days, delta) injected on the LAST n_days of the series. missing: (rows, cols, day_offsets_from_end) cells without data on those days."""
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    T = len(DATES)
    clim_doy = clim_curve()
    base = clim_doy[DATES.dayofyear.to_numpy() - 1][:, None, None] * np.ones((1, H, W), "float32")
    sst = (base + rng.normal(0, noise, (T, H, W))).astype("float32")
    for rows, cols, n, delta in events:
        sst[T - n:, rows[0]:rows[1], cols[0]:cols[1]] += delta
    if land_hot:
        sst[T - 10:][:, LAND] += 30.0
    has = np.ones((T, H, W), bool)
    has[:, LAND] = False
    for rows, cols, offs in missing:
        for o in offs:
            has[T - 1 - o, rows[0]:rows[1], cols[0]:cols[1]] = False
    channels = ["sst", "mask_sst"]
    norm = np.where(has, (sst - MU) / SD, 0).astype("float32")
    splits = {"train": DATES[DATES <= "2023-12-31"][:-400], "val": DATES[DATES <= "2023-12-31"][-400:], "test": DATES[DATES > "2023-12-31"]}
    (root / "cubes").mkdir(exist_ok=True)
    start = 0
    for name, idx in splits.items():
        n = len(idx)
        cube = np.zeros((n, 2, H, W), "float32")
        cube[:, 0] = norm[start:start + n]
        cube[:, 1] = has[start:start + n]
        np.save(root / "cubes" / f"{name}.npy", cube)
        np.save(root / "cubes" / f"{name}_dates.npy", idx.values.astype("datetime64[ns]"))
        start += n
    np.save(root / "land_mask.npy", LAND)
    meta = {"lat": LAT.tolist(), "lon": LON.tolist(), "resolution": 1.0, "channels": channels, "target_channel": "sst"}
    if source:
        meta["source"] = source
    (root / "meta.json").write_text(json.dumps(meta))
    (root / "stats.json").write_text(json.dumps({"train_period": ["2012-01-01", "2023-12-31"], "channels": {"sst": {"mean": MU, "std": SD}}}))
    clim = np.broadcast_to(clim_doy[:, None, None], (366, H, W)).copy()
    xr.Dataset({"sst": (("dayofyear", "lat", "lon"), clim)}, coords={"dayofyear": np.arange(1, 367), "lat": LAT, "lon": LON}).to_zarr(root / "climatology.zarr", mode="w")
    return root


@pytest.fixture(scope="module")
def warm(tmp_path_factory):
    """One event across the antimeridian (cols 6..11 = 178.5..183.5), 12 days, +3 degC; a second, smaller one far from it, only 4 days old (too short)."""
    root = build(tmp_path_factory.mktemp("pac_hw"), events=[((8, 14), (6, 12), 12, 3.0), ((4, 8), (13, 16), 4, 3.0)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        info = compute_heatwaves(root, None, "model", "pacific", "mhw-pacific")
    return root, info


def cells_of(info, k=0):
    return info["events"][k]


# ---------------------------------------------------------------------------------------------------- detect_runs edges
def series(pattern):
    return np.array([c == "x" for c in pattern], dtype=bool)[:, None]


def test_event_at_the_start_of_the_series_is_kept():
    mhw, rl = detect_runs(series("xxxxxx.........."))
    assert mhw[:6, 0].all() and not mhw[6:, 0].any() and rl[0, 0] == 1 and rl[5, 0] == 6


def test_event_at_the_end_of_the_series_is_kept_only_once_it_is_five_days_old():
    assert detect_runs(series("..........xxxxx"))[0][-5:, 0].all()
    assert not detect_runs(series("...........xxxx"))[0].any()


def test_minimum_duration_is_five_days_and_two_day_gaps_are_bridged():
    assert not detect_runs(series("..xxxx...."))[0].any()
    assert detect_runs(series("..xxxxx...."))[0].sum() == 5
    assert detect_runs(series("xxx..xx......"))[0].sum() == 7                         # 3 + gap of 2 + 2 days: one 7-day run


# ---------------------------------------------------------------------------------------------------- detector on the synthetic Pacific grid
def test_only_the_long_enough_event_is_reported_and_it_is_active_on_the_dataset_last_day(warm):
    root, info = warm
    assert info["latest_date"] == str(DATES[-1].date()) == "2024-03-31"               # the data date, never today
    assert len(info["events"]) == 1                                                   # the 4-day block has not reached 5 days
    ev = cells_of(info)
    assert ev["status"] == "ACTIVE" and ev["last_observed_date"] == "2024-03-31" and ev["dataset"] == "pacific" and ev["id"].startswith("mhw-pacific-2024-03-31-")


def test_event_across_the_antimeridian_is_one_event_with_continuous_longitudes(warm):
    _, info = warm
    ev = cells_of(info)
    assert ev["cells"] == 6 * 6
    b = ev["bbox"]
    assert b["lon_min"] == pytest.approx(178.0) and b["lon_max"] == pytest.approx(184.0)           # one box on the continuous axis, 180 inside it
    assert 180 < ev["centroid"]["lon"] < 182 and ev["centroid"]["lon_180"] == pytest.approx(ev["centroid"]["lon"] - 360)
    labels = np.load(root_of(warm) / "model" / "dashboard" / "heatwave_state.npz")["event_label"]
    assert (labels[8:14, 6:12] == 1).all() and labels.max() == 1                                     # cells either side of 180 carry the same event number


def root_of(w):
    return w[0]


def test_duration_max_anomaly_and_cumulative_intensity(warm):
    _, info = warm
    ev = cells_of(info)
    assert ev["duration_days"] == 12 and ev["start_date"] == "2024-03-20"
    assert ev["max_anomaly_c"] == pytest.approx(3.0, abs=1.0)                                       # injected +3 degC on noisy SST (sigma 0.3)
    assert ev["current_anomaly_c"] == pytest.approx(3.0, abs=0.4)
    assert ev["cumulative_intensity_c_days"] == pytest.approx(3.0 * 12, rel=0.1)
    assert ev["category"] == int(np.clip(ev["category"], 1, 4)) and ev["category_name"] == CATEGORY_NAMES[ev["category"]]


def test_area_uses_latitude_dependent_cell_areas(warm):
    _, info = warm
    ev = cells_of(info)
    expected = float((_cell_area_km2(LAT, 1.0)[8:14]).sum() * 6)
    assert ev["area_km2"] == pytest.approx(expected, rel=1e-3)
    a = _cell_area_km2(np.array([0.5, 60.5]), 1.0)
    assert a[1] < 0.55 * a[0]


def test_provenance_baseline_and_method_metadata(warm):
    _, info = warm
    assert info["dataset"] == "pacific" and info["baseline"] == ["2012-01-01", "2023-12-31"]
    assert info["threshold"]["percentile"] == 90.0 and info["min_duration_days"] == 5 and info["max_gap_days"] == 2
    assert info["is_observational"] is False and info["source"]["provider_id"] == "temporary_pacific_generated" and "NOAA" not in info["data_source"]
    assert "12 years" in info["method"] and info["grid"]["lon_min"] == LON.min() and info["build"]["seconds"] >= 0


def test_results_are_stored_apart_from_the_processed_cubes(warm):
    root, _ = warm
    out = root / "model" / "dashboard"
    assert {p.name for p in out.iterdir()} == {"heatwave.json", "heatwave_state.npz", "point_history.npz", "heatwave_history.json", "heatwave_cells.npz"}
    assert not (root / "cubes" / "heatwave_state.npz").exists()


def test_results_have_the_keys_the_backend_reads(warm):
    root, info = warm
    for k in ("grid", "latest_date", "events", "yearly", "daily", "ocean_area_km2", "active_area_km2", "active_share", "active_area_historical_rank_pct", "min_event_cells"):
        assert k in info
    st = np.load(root / "model" / "dashboard" / "heatwave_state.npz")
    assert {"run_len", "active", "event_label"} <= set(st.files) and st["run_len"].shape == (H, W)
    assert st["run_len"][8:14, 6:12].min() == 12 and st["run_len"][0, 10] == 0


def test_land_never_contributes(tmp_path):
    root = build(tmp_path, events=[((8, 14), (6, 12), 12, 3.0)], land_hot=True)             # land cells get +30 degC in the last 10 days
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        info = compute_heatwaves(root, None, "model", "pacific", "mhw-pacific")
    st = np.load(root / "model" / "dashboard" / "heatwave_state.npz")
    assert not st["active"][LAND].any() and (st["run_len"][LAND] == 0).all() and np.isnan(st["cur_anom"][LAND]).all()
    assert len(info["events"]) == 1 and info["events"][0]["cells"] == 36                    # land did not add cells, area or a second event
    ocean_area = float(_cell_area_km2(LAT, 1.0)[:, None].repeat(W, 1)[~LAND].sum())
    assert info["ocean_area_km2"] == pytest.approx(ocean_area, rel=1e-3)


def test_missing_day_inside_a_run_is_bridged_but_a_longer_gap_restarts_the_event(tmp_path):
    one = build(tmp_path / "one", events=[((8, 14), (6, 12), 12, 3.0)], missing=[((8, 14), (6, 12), [5])])                 # one missing day, 6 days before the end
    three = build(tmp_path / "three", events=[((8, 14), (6, 12), 12, 3.0)], missing=[((8, 14), (6, 12), [5, 6, 7])])      # three missing days
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a = compute_heatwaves(one, None, "model", "pacific", "mhw-pacific")["events"]
        b = compute_heatwaves(three, None, "model", "pacific", "mhw-pacific")["events"]
    assert len(a) == 1 and a[0]["duration_days"] == 12                                       # a gap of <= 2 days is bridged, as for the NE Pacific
    assert len(b) == 1 and b[0]["duration_days"] == 5                                        # 3 missing days break the run; only the days after it count
    st = np.load(three / "model" / "dashboard" / "heatwave_state.npz")
    assert not np.isnan(st["run_len"]).any()                                                 # missing never becomes NaN or an invented value in the run grid


def test_missing_data_is_not_a_zero_anomaly(tmp_path):
    root = build(tmp_path, events=[((8, 14), (6, 12), 12, 3.0)], missing=[((8, 10), (6, 12), [0])])         # no data on the LAST day for two rows
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        compute_heatwaves(root, None, "model", "pacific", "mhw-pacific")
    st = np.load(root / "model" / "dashboard" / "heatwave_state.npz")
    assert np.isnan(st["cur_anom"][8:10, 6:12]).all()                                        # no observation -> no anomaly (not 0.0)
    assert not st["active"][8:10, 6:12].any()                                                # and the cell is not "in a heatwave" on a day without data


def test_default_dataset_ids_and_source_stay_as_before_for_the_ne_pacific(tmp_path):
    root = build(tmp_path, events=[((8, 14), (6, 12), 12, 3.0)], source=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        info = compute_heatwaves(root)
    assert info["dataset"] == "ne_pacific" and info["events"][0]["id"].startswith("mhw-2024") and info["is_observational"] is True
    assert info["data_source"].startswith("NOAA OISST")


def test_pacific_config_labels_its_results_and_the_ne_config_does_not():
    from oceanmind_preprocess.config import load_config
    assert load_config(ROOT_CFG / "tests" / "config.stand_in_pacific.yaml").get("dataset_id") == "pacific"          # export-dashboard labels heatwave ids/results with it
    assert load_config(ROOT_CFG / "config.yaml").get("dataset_id", "ne_pacific") == "ne_pacific"


from pathlib import Path  # noqa: E402

ROOT_CFG = Path(__file__).resolve().parents[1]
