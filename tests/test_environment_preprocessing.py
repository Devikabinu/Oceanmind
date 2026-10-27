"""Provider -> existing preprocessing integration (oceanmind_environment -> oceanmind_preprocess). No forecasting, heatwave, risk or alert code involved."""
import json
import logging
import tracemalloc
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_environment import EnvironmentalDataProvider, build_provider
from oceanmind_preprocess import features
from oceanmind_preprocess.align import _standardise, land_mask_from, load_aligned, make_grid, normalize_longitude
from oceanmind_preprocess.clean import preclean
from oceanmind_preprocess.config import load_config
from oceanmind_preprocess.pipeline import build

ROOT = Path(__file__).resolve().parents[1]
T0, T1 = "2025-01-01", "2025-03-15"
SPLITS = {"train": [None, "2025-02-10"], "val": ["2025-02-11", "2025-02-28"], "test": ["2025-03-01", None]}


def pacific_cfg(out_dir, t0=T0, t1=T1, chunk=None):
    cfg = load_config(ROOT / "tests" / "config.stand_in_pacific.yaml")
    cfg.paths.out_dir = str(out_dir)
    cfg.time.update(start=t0, end=t1)
    cfg.splits = type(cfg.splits)({k: list(v) for k, v in SPLITS.items()})
    cfg.report.enabled = False
    if chunk:
        cfg.raw.provider_chunk_days = chunk
    return cfg


@pytest.fixture(scope="module")
def cfg(tmp_path_factory):
    return pacific_cfg(tmp_path_factory.mktemp("pacific_out"))


@pytest.fixture(scope="module")
def provider(cfg):
    return build_provider(cfg)


@pytest.fixture(scope="module")
def aligned(cfg):
    lat, lon = make_grid(cfg)
    return load_aligned(cfg, lat, lon, T0, T1)


@pytest.fixture(scope="module")
def built(cfg):
    return build(cfg)


class Variant(EnvironmentalDataProvider):
    """Wraps a real provider and breaks exactly one provider-contract convention, to prove preprocessing copes (or rejects it explicitly)."""

    def __init__(self, inner, flip_lat=False, lon="360", kelvin=False, drop_day=None, dup_day=None, unsorted=False, noon=False):
        self.inner, self.flip_lat, self.lon, self.kelvin = inner, flip_lat, lon, kelvin
        self.drop_day, self.dup_day, self.unsorted, self.noon = drop_day, dup_day, unsorted, noon

    def metadata(self): return self.inner.metadata()
    def grid(self): return self.inner.grid()
    def ocean_mask(self): return self.inner.ocean_mask()

    def available_dates(self):
        d = self.inner.available_dates()
        return d if self.drop_day is None else d[d != pd.Timestamp(self.drop_day)]

    def get_dataset(self, start=None, end=None, variables=("sst",), lon_convention="360"):
        ds = self.inner.get_dataset(start, end, variables, lon_convention=self.lon)
        if self.drop_day is not None:
            ds = ds.isel(time=np.flatnonzero(ds.time.values != np.datetime64(self.drop_day)))
        if self.dup_day is not None:
            ds = xr.concat([ds, ds.isel(time=[0])], "time")
        if self.unsorted:
            ds = ds.isel(time=slice(None, None, -1))
        if self.noon:
            ds = ds.assign_coords(time=ds.time + np.timedelta64(12, "h"))
        if self.flip_lat:
            ds = ds.isel(lat=slice(None, None, -1))
        if self.kelvin:
            ds["sst"] = ds["sst"] + 273.15
        return ds


def aligned_from(cfg, provider, t0=T0, t1=T1):
    lat, lon = make_grid(cfg)
    return load_aligned(cfg, lat, lon, t0, t1, provider=provider)


def cell(al, la, lo):
    return int(np.abs(al.lat - la).argmin()), int(np.abs(al.lon - lo).argmin())


# --- 1-3: the provider reaches preprocessing, SST and units intact -----------------------------------------------------------------
def test_config_selects_the_provider_and_the_grid_comes_from_it(cfg, provider):
    assert cfg.raw.source == "provider"
    lat, lon = provider.grid()
    assert (cfg.grid.lat_min, cfg.grid.lat_max, cfg.grid.lon_min, cfg.grid.lon_max, cfg.grid.resolution) == (lat[0], lat[-1], lon[0], lon[-1], 1.0)
    glat, glon = make_grid(cfg)
    assert np.allclose(glat, lat) and np.allclose(glon, lon)         # no second, incompatible grid


def test_sst_reaches_preprocessing_unchanged(cfg, provider, aligned):
    ds = provider.get_dataset(T0, T1)["sst"]
    assert aligned.data.keys() == {"sst"} and aligned.data["sst"].dtype == np.float32
    assert aligned.data["sst"].shape == (len(ds.time), 125, 190)
    assert np.array_equal(aligned.data["sst"], ds.values, equal_nan=True)      # same grid: not interpolated, not rescaled
    assert -2.0 <= np.nanmin(aligned.data["sst"]) and np.nanmax(aligned.data["sst"]) < 36           # degC, no unit conversion applied
    assert not aligned.nrt.any()                                                 # providers have no preliminary product


def test_injected_provider_and_config_provider_give_identical_data(cfg, provider, aligned):
    again = aligned_from(cfg, provider)
    assert np.array_equal(again.data["sst"], aligned.data["sst"], equal_nan=True)


def test_units_are_converted_only_at_the_preprocessing_boundary(cfg, provider, aligned):
    kelvin_cfg = pacific_cfg(Path(cfg.paths.out_dir))
    kelvin_cfg.raw.variables.sst.offset = -273.15                                # the existing scale/offset mechanism
    k = aligned_from(kelvin_cfg, Variant(provider, kelvin=True))
    assert np.allclose(k.data["sst"], aligned.data["sst"], atol=1e-3, equal_nan=True)


# --- 4: latitude ---------------------------------------------------------------------------------------------------------------------
def test_latitude_is_ascending_unique_and_spans_the_domain(aligned):
    assert np.all(np.diff(aligned.lat) > 0) and len(np.unique(aligned.lat)) == len(aligned.lat)
    assert aligned.lat[0] == -59.5 and aligned.lat[-1] == 64.5


def test_flipped_latitude_order_does_not_corrupt_the_data(cfg, provider, aligned):
    flipped = aligned_from(cfg, Variant(provider, flip_lat=True))
    assert np.array_equal(flipped.data["sst"], aligned.data["sst"], equal_nan=True)


# --- 5-8: longitude and the antimeridian ---------------------------------------------------------------------------------------------
def test_longitude_axis_is_ascending_and_contiguous_across_180(aligned):
    assert np.all(np.diff(aligned.lon) > 0)
    assert np.allclose(np.diff(aligned.lon), 1.0)                                # no artificial gap anywhere, in particular at 180
    assert aligned.lon[0] == 100.5 and aligned.lon[-1] == 289.5
    j = int(np.flatnonzero(aligned.lon == 179.5)[0])
    assert aligned.lon[j + 1] == 180.5                                           # 179E and 181E (= 179W) are neighbouring columns


@pytest.mark.parametrize("lon_convention", ["360", "180"])
def test_both_provider_longitude_conventions_normalise_to_the_same_axis(cfg, provider, aligned, lon_convention):
    al = aligned_from(cfg, Variant(provider, lon=lon_convention))
    assert np.array_equal(al.lon, aligned.lon) and np.array_equal(al.data["sst"], aligned.data["sst"], equal_nan=True)


def test_data_are_spatially_continuous_across_the_antimeridian(aligned):
    sst = aligned.data["sst"][10]
    j = int(np.flatnonzero(aligned.lon == 179.5)[0])
    across = np.abs(sst[:, j + 1] - sst[:, j])
    elsewhere = np.abs(np.diff(sst, axis=1))
    elsewhere = np.delete(elsewhere, j, axis=1)
    assert np.isfinite(across).sum() > 50                                        # lots of open ocean on both sides of the seam
    assert np.nanmean(across) < 2 * np.nanmean(elsewhere)                        # the seam is not a discontinuity


def test_normalize_longitude_keeps_neighbours_adjacent():
    lon = np.arange(-179.5, 180, 1.0)                                            # a global -180..180 axis
    da = xr.DataArray(lon[None, None, :] * np.ones((1, 2, 1)), dims=("time", "lat", "lon"), coords={"time": [0], "lat": [0.0, 1.0], "lon": lon})
    out = normalize_longitude(da, lon_start=99.0)
    assert out.lon.values[0] == 99.5 and np.all(np.diff(out.lon.values) == 1.0)  # continuous, ascending
    i = int(np.flatnonzero(out.lon.values == 179.5)[0])
    assert out.lon.values[i + 1] == 180.5 and out.values[0, 0, i + 1] == -179.5  # the cell labelled 180.5 is the old -179.5 cell
    # a sorted -180..180 axis (the old behaviour) would have put -179.5 first and 179.5 last: the Pacific would be torn apart
    legacy = da.sortby("lon")
    assert legacy.lon.values[0] == -179.5 and legacy.lon.values[-1] == 179.5


def test_domains_inside_one_hemisphere_are_not_altered_by_normalisation():
    lon = np.arange(-179.875, 180, 0.25)
    da = xr.DataArray(np.arange(lon.size, dtype="float32")[None, None, :], dims=("time", "lat", "lon"), coords={"time": [0], "lat": [0.0], "lon": lon})
    out = normalize_longitude(da, lon_start=-161.0)
    inside = out.sel(lon=slice(-160, -120))
    assert np.array_equal(inside.lon.values, da.sel(lon=slice(-160, -120)).lon.values)       # bit-identical labels in the NE Pacific window
    assert np.array_equal(inside.values, da.sel(lon=slice(-160, -120)).values)


# --- 9-10: time ----------------------------------------------------------------------------------------------------------------------
def test_timestamps_are_sorted_unique_daily_midnight(aligned):
    t = aligned.times
    assert t.is_monotonic_increasing and t.is_unique and (t == t.floor("D")).all()
    assert (np.diff(t.values) == np.timedelta64(1, "D")).all() and t[0] == pd.Timestamp(T0) and t[-1] == pd.Timestamp(T1)


@pytest.mark.parametrize("kw,msg", [({"dup_day": True}, "duplicate timestamps"), ({"unsorted": True}, "not sorted"), ({"noon": True}, "midnight")])
def test_bad_provider_timestamps_are_rejected_not_silently_averaged(cfg, provider, kw, msg):
    with pytest.raises(ValueError, match=msg):
        aligned_from(cfg, Variant(provider, **kw), "2025-01-01", "2025-01-10")


def test_missing_days_are_detected_and_left_nan_as_with_stored_data(cfg, provider, caplog):
    with caplog.at_level(logging.WARNING, logger="oceanmind_preprocess"):
        al = aligned_from(cfg, Variant(provider, drop_day="2025-01-05"), "2025-01-01", "2025-01-10")
    assert any("missing 1 day" in r.message for r in caplog.records)
    assert len(al.times) == 10                                                   # the axis stays complete: the day is not dropped...
    i = list(al.times).index(pd.Timestamp("2025-01-05"))
    assert np.isnan(al.data["sst"][i]).all()                                     # ...and not invented
    assert np.isfinite(al.data["sst"][i - 1][provider.ocean_mask()]).all()


# --- 11-12: land stays invalid ---------------------------------------------------------------------------------------------------------
LAND = {"australia": (-25, 135.5), "siberia": (60, 110.5), "north_america": (45, 260.5)}
OCEAN = {"western_pacific": (30, 150.5), "central_pacific": (5, 185.5), "eastern_pacific": (-10, 275.5), "tropical_atlantic_side_excluded_ocean": (0, 180.5)}


def test_land_stays_nan_and_ocean_stays_valid_through_alignment_and_cleaning(cfg, provider, aligned):
    mask = provider.ocean_mask()
    ocean_cells = ~land_mask_from(aligned.data["sst"])
    assert np.array_equal(ocean_cells, mask)                                     # the pipeline derives exactly the provider's mask
    assert np.isnan(aligned.data["sst"][:, ~mask]).all() and np.isfinite(aligned.data["sst"][:, mask]).all()
    for name, (la, lo) in LAND.items():
        assert not ocean_cells[cell(aligned, la, lo)], name
    limits = {"sst": (-2.0, 40.0)}
    clean, _ = preclean(cfg, aligned.data, ocean_cells, limits, [slice(0, len(aligned.times))])
    assert np.isnan(clean["sst"][:, ~mask]).all()                                # gap-filling/clipping never turns land into data
    assert np.isfinite(clean["sst"][:, mask]).all()
    zero = aligned.data["sst"][:, mask] == 0
    assert not zero.all()                                                        # near-zero temperatures are values, NaN is missing: distinct


# --- 13-15: climatology, anomaly, Pacific-wide survival, via the real build ----------------------------------------------------------
def test_build_outputs_have_the_format_downstream_code_expects(cfg, built):
    o = Path(cfg.paths.out_dir)
    for f in ("land_mask.npy", "stats.json", "meta.json", "climatology.zarr", "cubes/train.npy", "cubes/val.npy", "cubes/test.npy", "cubes/train_dates.npy",
              "forecast/windows_train.parquet", "anomaly/index_train.parquet", "missing_report.json"):
        assert (o / f).exists(), f
    meta = json.loads((o / "meta.json").read_text())
    assert meta["channels"] == ["sst", "sst_anom", "sst_grad", "doy_sin", "doy_cos", "mask_sst"]       # same channel layout as the NE Pacific build
    assert len(meta["lat"]) == 125 and len(meta["lon"]) == 190 and meta["resolution"] == 1.0
    assert np.allclose(np.diff(meta["lon"]), 1.0)
    assert np.load(o / "cubes" / "train.npy", mmap_mode="r").shape[1:] == (6, 125, 190)


def test_climatology_comes_from_the_existing_train_only_processing(cfg, built, aligned, provider):
    o = Path(cfg.paths.out_dir)
    mask = provider.ocean_mask()
    clim = xr.open_zarr(o / "climatology.zarr")["sst"].values                     # (366, H, W)
    assert clim.shape == (366, 125, 190) and np.isnan(clim[:, ~mask]).all()
    train_days = pd.date_range(T0, "2025-02-10")
    assert np.isfinite(clim[train_days.dayofyear.values - 1][:, mask]).all()
    lim = json.loads((o / "stats.json").read_text())["clip_limits"]["sst"]
    clean, _ = preclean(cfg, aligned.data, mask, {"sst": tuple(lim)}, [slice(0, 41), slice(41, 59), slice(59, len(aligned.times))])
    _, expected = features.daily_climatology(clean["sst"][:len(train_days)], aligned.times[:len(train_days)], cfg.climatology.smooth_sigma_days)
    assert np.allclose(clim, expected, equal_nan=True, atol=1e-4)                  # identical to calling the existing function directly


def test_anomaly_is_sst_minus_climatology_via_the_existing_feature_code(cfg, built, provider):
    o = Path(cfg.paths.out_dir)
    st = json.loads((o / "stats.json").read_text())
    meta = json.loads((o / "meta.json").read_text())
    names, mask = meta["channels"], provider.ocean_mask()
    clim = xr.open_zarr(o / "climatology.zarr")["sst"].values
    cube = np.load(o / "cubes" / "val.npy", mmap_mode="r")
    dates = pd.DatetimeIndex(np.load(o / "cubes" / "val_dates.npy"))
    sst = cube[:, names.index("sst")] * st["channels"]["sst"]["std"] + st["channels"]["sst"]["mean"]
    anom = cube[:, names.index("sst_anom")] * st["channels"]["sst_anom"]["std"] + st["channels"]["sst_anom"]["mean"]
    expected = sst - clim[dates.dayofyear.values - 1]
    assert np.allclose(anom[:, mask], expected[:, mask], atol=2e-3)
    assert np.nanmax(np.abs(anom[:, mask])) > 0.5                                  # not a field of zeros


def test_pacific_wide_cells_survive_and_land_stays_invalid_after_build(cfg, built, provider):
    o = Path(cfg.paths.out_dir)
    meta = json.loads((o / "meta.json").read_text())
    lat, lon, names = np.array(meta["lat"]), np.array(meta["lon"]), meta["channels"]
    land = np.load(o / "land_mask.npy")
    assert (~land).sum() == provider.metadata().valid_cells == 16165               # every provider ocean cell is a processed ocean cell
    cube = np.load(o / "cubes" / "train.npy", mmap_mode="r")
    ii = lambda la, lo: (int(np.abs(lat - la).argmin()), int(np.abs(lon - lo).argmin()))  # noqa: E731
    for name, (la, lo) in {"western_pacific": (30, 150.5), "central_pacific": (5, 185.5), "eastern_pacific": (-10, 275.5)}.items():
        i, j = ii(la, lo)
        assert not land[i, j], name
        assert (cube[:, names.index("mask_sst"), i, j] == 1).all(), name           # valid data on every day
        assert np.abs(cube[:, names.index("sst"), i, j]).max() > 0, name
    for name, (la, lo) in LAND.items():
        i, j = ii(la, lo)
        assert land[i, j], name
        assert (cube[:, :, i, j] == 0).all(), name                                 # land never carries data
    # the old NE Pacific window (20-50N, 160-120W = 200-240E) is just a small part of what survives
    ocean_lat, ocean_lon = lat[(~land).any(axis=1)], lon[(~land).any(axis=0)]
    assert ocean_lat.min() < -50 and ocean_lat.max() > 60 and ocean_lon.min() < 110 and ocean_lon.max() > 285
    ne = (~land)[np.ix_((lat >= 20) & (lat <= 50), (lon >= 200) & (lon <= 240))].sum()
    assert (~land).sum() > 6 * ne


def test_no_geographic_limits_are_hard_coded_in_the_preprocessing_code():
    import re
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "oceanmind_preprocess").glob("*.py") if p.name != "ingest.py")
    assert not re.search(r"\b(?:20\.125|49\.875|159\.875|120\.125)\b", src)
    assert "temporary_pacific" not in src and "TemporaryPacific" not in src          # the pipeline knows only the provider interface
    assert not re.search(r"provider(?:_id)?\s*==", src) and "provider_type" not in src


# --- 16: existing (stores based) behaviour --------------------------------------------------------------------------------------------
def test_existing_ne_pacific_configuration_is_unchanged():
    c = load_config(ROOT / "config.yaml")
    assert c.raw.source == "stores"
    assert (c.grid.lat_min, c.grid.lat_max, c.grid.lon_min, c.grid.lon_max, c.grid.resolution) == (20.125, 49.875, -159.875, -120.125, 0.25)
    lat, lon = make_grid(c)
    assert (len(lat), len(lon)) == (120, 160) and lon[0] == -159.875


@pytest.mark.parametrize("convention", ["pm180", "0to360"])
def test_stored_sources_in_either_convention_still_give_the_ne_pacific_window(convention):
    lon_src = np.arange(-179.875, 180, 0.25)
    lat_src = np.arange(15.125, 55, 0.25)
    field = (lat_src[:, None] * 0.1 + np.where(lon_src < 0, lon_src + 360, lon_src)[None, :] * 0.01).astype("float32")
    if convention == "0to360":
        order = np.argsort(np.where(lon_src < 0, lon_src + 360, lon_src))
        lon_axis, field = np.where(lon_src < 0, lon_src + 360, lon_src)[order], field[:, order]
    else:
        lon_axis = lon_src
    da = xr.DataArray(field[None], dims=("time", "latitude", "longitude"), coords={"time": [pd.Timestamp("2025-01-01")], "latitude": lat_src, "longitude": lon_axis})
    out = _standardise(da, {}, lon_start=-160.875).sel(lat=slice(20, 50), lon=slice(-160, -120))
    want = np.arange(-159.875, -120, 0.25)
    assert np.allclose(out.lon.values, want) and out.shape[2] == 160
    i = int(np.abs(out.lat.values - 30.125).argmin())
    assert np.allclose(out.values[0, i], (30.125 * 0.1 + (want + 360) * 0.01), atol=1e-4)


# --- chunking and memory ---------------------------------------------------------------------------------------------------------------
def test_time_chunking_does_not_change_the_result(cfg, provider, aligned):
    small = pacific_cfg(Path(cfg.paths.out_dir), chunk=17)
    chunked = aligned_from(small, provider)
    assert np.array_equal(chunked.data["sst"], aligned.data["sst"], equal_nan=True)


def test_a_year_of_pacific_data_preprocesses_with_practical_memory(tmp_path):
    cfg = pacific_cfg(tmp_path, "2025-01-01", "2025-12-31", chunk=92)
    cfg.splits = type(cfg.splits)({"train": [None, "2025-08-31"], "val": ["2025-09-01", "2025-10-15"], "test": ["2025-10-16", None]})
    tracemalloc.start()
    summary = build(cfg)
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    assert summary["splits"]["train"]["days"] == 243 and summary["splits"]["test"]["days"] == 77
    assert peak < 1.5e9, f"peak {peak / 1e6:.0f} MB"                               # raw + cleaned (T,H,W) arrays only; the feature cube is streamed to disk
    assert (tmp_path / "cubes" / "train.npy").stat().st_size > 0


# --- the other existing consumer of the loader: the inference path ---------------------------------------------------------------------------
def test_inference_path_also_reads_from_the_provider(cfg, built, provider):
    from oceanmind_preprocess.align import latest_available_date
    from oceanmind_preprocess.inference import build_latest_window

    assert latest_available_date(cfg) == provider.latest_timestamp()               # taken from the provider, not from "today"
    w = build_latest_window("2025-03-10", config=cfg)
    assert w["x"].shape == (7, 6, 125, 190) and w["as_of"] == "2025-03-10" and w["n_nrt_days"] == 0
    assert np.isfinite(w["x"]).all() and w["ocean"].sum() == 16165


def test_meta_records_the_provider_so_the_api_can_label_generated_data(cfg, built, provider):
    meta = json.loads((Path(cfg.paths.out_dir) / "meta.json").read_text())
    assert meta["source"] == json.loads(json.dumps(provider.metadata().to_dict()))
    assert meta["source"]["is_observational"] is False
    assert "antimeridian" in meta["lon_convention"]
