import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_preprocess.biodiversity import grid_obis
from oceanmind_preprocess.datasets import AnomalyDataset, ForecastDataset
from oceanmind_preprocess.inference import build_latest_window
from oceanmind_preprocess.pipeline import build

from conftest import make_cfg, make_raw


def out(cfg):
    return Path(cfg.paths.out_dir)


def test_artifacts_exist(built):
    cfg, _ = built
    o = out(cfg)
    for f in ("land_mask.npy", "stats.json", "meta.json", "climatology.zarr", "preprocess_report.md",
              "cubes/train.npy", "forecast/windows_val.parquet", "anomaly/index_test.parquet",
              "biodiversity/obis_monthly.parquet", "biodiversity/obis_monthly.zarr",
              "figures/missing_map.png", "figures/climatology_example.png", "figures/sst_before_after.png", "figures/splits.png"):
        assert (o / f).exists(), f


def test_land_mask_and_no_nans(built):
    cfg, _ = built
    o = out(cfg)
    land = np.load(o / "land_mask.npy")
    assert land.sum() > 0 and (~land).sum() > land.sum()
    for s in ("train", "val", "test"):
        cube = np.load(o / "cubes" / f"{s}.npy")
        assert np.isfinite(cube).all()
        assert (cube[:, :, land] == 0).all()                      # land is never filled with data


def test_train_normalisation_and_stats_json(built):
    cfg, summary = built
    for ch, (m, s) in summary["moments"].items():
        assert abs(m) < 1e-3 and abs(s - 1) < 1e-3, ch
    st = json.loads((out(cfg) / "stats.json").read_text())
    assert st["train_period"][1] == "2020-12-31" and "sst" in st["channels"] and "sst" in st["clip_limits"]


def test_chlorophyll_is_log10_and_units_converted(built):
    cfg, _ = built
    st = json.loads((out(cfg) / "stats.json").read_text())
    assert -3 < st["clip_limits"]["chl"][1] < 1     # log10 of ~0.1 mg/m3, not a raw concentration
    assert st["clip_limits"]["sst"][0] > 20          # Kelvin offset applied
    assert 150 < st["channels"]["oxy"]["mean"] < 260  # surface level selected, not the +50 deep level


def test_splits_do_not_overlap_and_windows_stay_inside(built):
    cfg, _ = built
    o = out(cfg)
    rng = {}
    for s in ("train", "val", "test"):
        d = np.load(o / "cubes" / f"{s}_dates.npy")
        rng[s] = (d.min(), d.max())
        w = pd.read_parquet(o / "forecast" / f"windows_{s}.parquet")
        assert len(w) > 0
        assert w.start_date.min() >= d.min() and w.target_last_date.max() <= d.max()
    assert rng["train"][1] < rng["val"][0] and rng["val"][1] < rng["test"][0]
    assert str(rng["test"][1])[:10] == "2021-05-31"            # latest FINAL date (NRT not used for build)


def test_gap_report(built):
    _, summary = built
    f = summary["fill"]["sst"]
    assert f["filled"] > 0 and f["missing_after"] < f["missing_before"]
    assert 0 < f["pct_of_missing_filled"] <= 100


def test_forecast_dataset_lazy_shapes(built):
    cfg, _ = built
    ds = ForecastDataset(out(cfg), "val")
    assert ds._cube is None                                      # nothing loaded until first item
    item = ds[0]
    H, W = np.load(out(cfg) / "land_mask.npy").shape
    assert item["x"].shape == (7, len(ds.channels), H, W) and item["y"].shape == (7, H, W)
    assert np.isfinite(item["x"].numpy()).all()
    from torch.utils.data import DataLoader
    b = next(iter(DataLoader(ds, batch_size=4)))
    assert b["x"].shape[0] == 4


def test_forecast_target_is_sst_h_days_ahead(built):
    cfg, _ = built
    o = out(cfg)
    ds = ForecastDataset(o, "val")
    names = json.loads((o / "meta.json").read_text())["channels"]
    cube = np.load(o / "cubes" / "val.npy")
    s = int(ds.starts[3])
    item = ds[3]
    assert np.array_equal(item["y"].numpy()[0], cube[s + 7, names.index("sst")])      # horizon 1
    assert np.array_equal(item["y"].numpy()[6], cube[s + 13, names.index("sst")])     # horizon 7


def test_anomaly_dataset(built):
    cfg, _ = built
    ds = AnomalyDataset(out(cfg), "test")
    item = ds[0]
    assert len(ds) > 0 and item["x"].shape == (8, 8, 8)           # 8 channels (4 masks incl.), 8x8 patch


def test_no_leakage_from_test_period(raw_dir, tmp_path):
    """Changing only test-period data must not change anything fitted on, or derived for, train/val."""
    raw2 = tmp_path / "raw2"
    raw2.mkdir()
    make_raw(raw2, perturb_from=pd.Timestamp("2021-04-01"))
    cfg1 = make_cfg(tmp_path, raw_dir=raw_dir, out_dir=tmp_path / "out1")
    cfg2 = make_cfg(tmp_path, raw_dir=raw2, out_dir=tmp_path / "out2")
    build(cfg1)
    build(cfg2)
    s1 = json.loads((out(cfg1) / "stats.json").read_text())
    s2 = json.loads((out(cfg2) / "stats.json").read_text())
    assert s1 == s2
    for s in ("train", "val"):
        assert np.array_equal(np.load(out(cfg1) / "cubes" / f"{s}.npy"), np.load(out(cfg2) / "cubes" / f"{s}.npy"))
    assert not np.array_equal(np.load(out(cfg1) / "cubes" / "test.npy"), np.load(out(cfg2) / "cubes" / "test.npy"))
    assert xr.open_zarr(out(cfg1) / "climatology.zarr").load().equals(xr.open_zarr(out(cfg2) / "climatology.zarr").load())


def test_inference_counts_nrt_days(built):
    cfg, _ = built
    w = build_latest_window("2021-06-10", cfg)           # FINAL ends 2021-05-31 -> all 7 days NRT
    assert w["n_nrt_days"] == 7 and w["x"].shape[0] == 7 and np.isfinite(w["x"]).all()
    w = build_latest_window("2021-06-02", cfg)           # 05-27..05-31 FINAL, 06-01..06-02 NRT
    assert w["n_nrt_days"] == 2 and w["nrt_flags"] == [False] * 5 + [True] * 2
    w = build_latest_window(None, cfg)                   # default = latest available date
    assert w["as_of"] == "2021-06-30"
    with pytest.raises(ValueError):
        build_latest_window("2021-07-15", cfg)


def test_inference_matches_training_cube(built):
    cfg, _ = built
    o = out(cfg)
    w = build_latest_window("2021-05-20", cfg)
    idx = pd.read_parquet(o / "forecast" / "windows_test.parquet")
    row = idx[idx.input_end_date == pd.Timestamp("2021-05-20")]
    assert len(row) == 1 and w["n_nrt_days"] == 0
    cube = np.load(o / "cubes" / "test.npy", mmap_mode="r")
    names = json.loads((o / "meta.json").read_text())["channels"]
    s = int(row.start_idx.iloc[0])
    train_x = np.asarray(cube[s:s + 7])
    both = (train_x[:, names.index("mask_sst")] > 0) & (w["x"][:, w["channels"].index("mask_sst")] > 0)
    assert both.mean() > 0.5
    for ch in ("sst", "sst_anom", "doy_sin"):
        a, b = train_x[:, names.index(ch)], w["x"][:, w["channels"].index(ch)]
        assert np.allclose(a[both], b[both], atol=1e-4), ch


def test_biodiversity_outputs(built):
    cfg, _ = built
    tab = pd.read_parquet(out(cfg) / "biodiversity" / "obis_monthly.parquet")
    assert {"n_records", "richness", "effort", "log_effort", "n_sampling_days"} <= set(tab.columns)
    assert (tab.richness <= tab.n_species_records).all() and (tab.n_species_records <= tab.n_records).all()
    z = xr.open_zarr(out(cfg) / "biodiversity" / "obis_monthly.zarr").load()
    assert z.n_records.sum() == tab.n_records.sum()
    assert z.richness.where(z.n_records == 0).isnull().all()


def test_grid_obis_binning(tmp_path):
    cfg = make_cfg(tmp_path)
    lat, lon = np.array([10.0, 10.25]), np.array([70.0, 70.25])
    df = pd.DataFrame({"decimalLatitude": [10.01, 10.02, 10.24, 50.0], "decimalLongitude": [70.0, 70.1, 70.26, 70.0],
                       "eventDate": ["2020-01-03", "2020-01-20", "2020-01-05", "2020-01-01"],
                       "species": ["x", "y", "x", "z"], "datasetID": ["a", "a", "b", "a"]})
    t = grid_obis(df, cfg, lat, lon)
    c0 = t[(t.lat_idx == 0) & (t.lon_idx == 0)].iloc[0]
    assert len(t) == 2 and c0.n_records == 2 and c0.richness == 2 and c0.n_sampling_days == 2
