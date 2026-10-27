"""Tests for the temporary Pacific environmental provider (oceanmind_environment). Only the provider layer is covered here."""
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from oceanmind_environment import DateNotAvailable, EnvironmentalDataProvider, PacificDomainConfig, TemporaryPacificProvider, build_from_cfg
from oceanmind_environment.base import ProviderMetadata
from oceanmind_preprocess.config import load_config

LAT_MIN, LAT_MAX, LON_MIN, LON_MAX = -60.0, 65.0, 100.0, 290.0


def make(res=2.5, start="2026-08-01", end="2026-10-15", seed=7):
    return TemporaryPacificProvider(PacificDomainConfig(
        provider="temporary_pacific", lat_min=LAT_MIN, lat_max=LAT_MAX, lon_min=LON_MIN, lon_max=LON_MAX, resolution_deg=res,
        temporal_resolution="1D", start_date=start, end_date=end, seed=seed, mask_source="builtin_polygons"))


@pytest.fixture(scope="module")
def prov():
    return make()


def cell(p, lat, lon):
    la, lo = p.grid()
    return int(np.abs(la - lat).argmin()), int(np.abs(lo - lon).argmin())


# --- domain, grid, resolution ---------------------------------------------------------------------------------------------------
def test_pacific_domain_dimensions_and_extent(prov):
    lat, lon = prov.grid()
    assert lat.shape == (int((LAT_MAX - LAT_MIN) / 2.5),) and lon.shape == (int((LON_MAX - LON_MIN) / 2.5),)
    assert lat[0] == pytest.approx(LAT_MIN + 1.25) and lat[-1] == pytest.approx(LAT_MAX - 1.25)      # cell centres
    assert lon[0] == pytest.approx(LON_MIN + 1.25) and lon[-1] == pytest.approx(LON_MAX - 1.25)
    assert np.all(np.diff(lat) > 0) and np.all(np.diff(lon) > 0)                              # ascending, contiguous across 180E
    assert lon.min() < 180 < lon.max()                                                        # the Pacific straddles the antimeridian
    ds = prov.get_dataset()
    assert ds["sst"].dims == ("time", "lat", "lon") and ds["sst"].shape == (1, len(lat), len(lon))
    assert ds["sst"].dtype == np.float32


def test_resolution_is_configurable_without_code_changes():
    coarse, fine = make(res=5.0), make(res=2.5)
    assert coarse.get_sst().shape == (25, 38) and fine.get_sst().shape == (50, 76)
    assert coarse.metadata().resolution_deg == 5.0 and fine.metadata().resolution_deg == 2.5
    assert coarse.metadata().total_cells < fine.metadata().total_cells


def test_invalid_configuration_is_rejected():
    kw = dict(provider="temporary_pacific", lat_min=-60, lat_max=65, lon_min=100, lon_max=290, resolution_deg=2.5, temporal_resolution="1D",
              start_date="2026-01-01", end_date="2026-02-01", seed=1, mask_source="builtin_polygons")
    for bad in ({"lat_min": 70}, {"lon_max": 400}, {"resolution_deg": 0}, {"resolution_deg": 3.0}, {"temporal_resolution": "1H"}, {"start_date": "2027-01-01"}):
        with pytest.raises(ValueError):
            PacificDomainConfig(**{**kw, **bad})
    with pytest.raises(ValueError):
        TemporaryPacificProvider(PacificDomainConfig(**{**kw, "provider": "real_pacific"}))


def test_project_config_yaml_defines_the_domain():
    p = build_from_cfg(load_config("config.yaml"))
    m = p.metadata()
    assert m.extent == {"lat_min": -60.0, "lat_max": 65.0, "lon_min": 100.0, "lon_max": 290.0}
    assert m.provider_id == "temporary_pacific_generated" and m.grid_shape == (125, 190)


# --- determinism --------------------------------------------------------------------------------------------------------------------
def test_generation_is_deterministic():
    a, b = make(), make()
    for var in ("sst", "climatology", "anomaly"):
        x = a.get_dataset("2026-09-01", "2026-09-10", (var,))[var].values
        y = b.get_dataset("2026-09-01", "2026-09-10", (var,))[var].values
        assert np.array_equal(x, y, equal_nan=True)
    again = a.get_dataset("2026-09-01", "2026-09-10")["sst"].values       # the same provider asked twice
    assert np.array_equal(again, a.get_dataset("2026-09-01", "2026-09-10")["sst"].values, equal_nan=True)
    assert not np.array_equal(make(seed=8).get_sst().values, a.get_sst().values, equal_nan=True)   # the seed is what fixes the field


def test_any_date_can_be_requested_directly_and_matches_a_range():
    p = make()
    rng = p.get_dataset("2026-09-01", "2026-09-05")["sst"]
    single = p.get_sst("2026-09-03")
    assert np.array_equal(rng.sel(time="2026-09-03").values, single.values, equal_nan=True)


# --- spatial and temporal structure ---------------------------------------------------------------------------------------------
def test_sst_varies_spatially_and_is_smooth():
    p = make()
    sst = p.get_sst().values
    mask = p.ocean_mask()
    assert np.nanstd(sst[mask]) > 4.0
    # smoothness: neighbouring ocean cells differ far less than the basin-wide spread (not independent per-cell noise)
    dx = np.abs(np.diff(sst, axis=1))
    both = mask[:, 1:] & mask[:, :-1]
    assert np.nanmean(dx[both]) < 0.4 * np.nanstd(sst[mask])


def test_tropics_are_warmer_than_high_latitudes():
    p = make()
    sst = p.get_sst()
    trop = sst.sel(lat=slice(-10, 10)).mean().item()
    north = sst.sel(lat=slice(50, 65)).mean().item()
    south = sst.sel(lat=slice(-60, -50)).mean().item()
    assert trop > 25 and trop - north > 15 and trop - south > 15
    assert abs(north - south) > 0.5          # the hemispheres are not mirror images


def test_warm_pool_is_warmer_than_eastern_cold_tongue():
    p = make()
    sst = p.get_sst()
    assert sst.sel(lat=0, lon=150, method="nearest").item() > sst.sel(lat=0, lon=250, method="nearest").item() + 1.5


def test_sst_changes_smoothly_through_time():
    p = make()
    ds = p.get_dataset("2026-08-01", "2026-10-15")["sst"]
    mask = p.ocean_mask()
    diff = ds.diff("time").values[:, mask]
    assert np.abs(diff).mean() > 0.0                                       # it does change
    assert np.abs(diff).mean() < 0.4                                       # but only by small steps
    first = ds.isel(time=0).values[mask]
    day2, day30, day75 = (ds.isel(time=i).values[mask] for i in (1, 29, 74))
    r = lambda a, b: np.corrcoef(a, b)[0, 1]                               # noqa: E731
    assert r(first, day2) > 0.999 and r(first, day2) > r(first, day30) > r(first, day75) - 1e-9  # similarity falls with separation


def test_seasonal_cycle_has_opposite_phase_in_the_hemispheres():
    p = make(start="2025-01-01", end="2026-10-15")
    feb, aug = p.climatology_field(50), p.climatology_field(235)
    n, s = cell(p, 40, 180), cell(p, -40, 180)
    assert aug[n] > feb[n] and feb[s] > aug[s]


def test_latest_day_contains_active_warm_anomalies_that_were_absent_earlier():
    p = make(start="2026-01-01")
    now, before = p.anomaly_field("2026-10-15"), p.anomaly_field("2026-01-10")
    k = cell(p, 34, 237)                                                   # California Current feature
    assert now[k] > 1.5 and now[k] - before[k] > 1.2
    assert np.nanmax(now) > 2.0


def test_leap_day_and_day_366_are_handled():
    p = make(start="2023-01-01", end="2024-12-31")
    assert np.isfinite(p.get_sst("2024-02-29")).any() and np.isfinite(p.get_sst("2024-12-31")).any()


# --- mask ---------------------------------------------------------------------------------------------------------------------------
def test_land_is_nan_and_ocean_is_valid(prov):
    ds = prov.get_dataset("2026-10-01", "2026-10-03", ("sst", "climatology", "anomaly"))
    mask = prov.ocean_mask()
    for v in ("sst", "climatology", "anomaly"):
        a = ds[v].values
        assert np.isnan(a[:, ~mask]).all()                                 # land never receives a value
        assert np.isfinite(a[:, mask]).all()                               # every ocean cell does
    for name, (la, lo) in {"siberia": (60, 110), "australia_interior": (-25, 135), "north_america": (45, 260), "south_america": (-10, 285),
                           "china": (30, 112)}.items():
        assert not mask[cell(prov, la, lo)], name
    for name, (la, lo) in {"mid_pacific": (0, 180), "north_pacific": (35, 180), "south_pacific": (-35, 200), "bering_sea": (58, 185),
                           "coral_sea": (-15, 155), "east_china_sea": (28, 126), "off_peru": (-12, 275), "tasman_sea": (-38, 165)}.items():
        assert mask[cell(prov, la, lo)], name
    frac = mask.mean()
    assert 0.5 < frac < 0.85


def test_non_pacific_waters_are_excluded():
    p = make()
    for name, (la, lo) in {"indian_ocean_south_of_java": (-20, 105), "great_australian_bight": (-35, 130), "gulf_of_mexico": (25, 270),
                           "caribbean": (15, 290)}.items():
        assert not p.ocean_mask()[cell(p, la, lo)], name


def test_land_and_mask_are_independent_of_time(prov):
    a, b = prov.get_sst("2026-09-01"), prov.get_sst("2026-10-10")
    assert np.array_equal(np.isnan(a.values), np.isnan(b.values))


# --- metadata -----------------------------------------------------------------------------------------------------------------------
def test_metadata_is_accurate_and_never_claims_an_external_source(prov):
    m = prov.metadata()
    assert isinstance(m, ProviderMetadata)
    assert m.provider_id == "temporary_pacific_generated" and m.provider_type == "generated_temporary" and m.is_observational is False
    assert m.units == "degree_C" and m.variables["sst"]["units"] == "degree_C"
    assert m.extent == {"lat_min": LAT_MIN, "lat_max": LAT_MAX, "lon_min": LON_MIN, "lon_max": LON_MAX}
    assert m.resolution_deg == 2.5 and m.temporal_resolution == "1D"
    assert m.temporal_coverage == {"start": "2026-08-01", "end": "2026-10-15", "n_timestamps": 76}
    assert m.latest_timestamp == "2026-10-15"
    assert m.total_cells == prov.ocean_mask().size and m.valid_cells == int(prov.ocean_mask().sum())
    text = str(m.to_dict()).lower()
    assert "generated" in text
    for external in ("noaa", "copernicus", "obis", "gbif", "oisst"):
        assert external not in text.replace("not attribute to any external source", "")
    ds = prov.get_dataset()
    assert ds.attrs["is_observational"] == 0 and "not an observation" in ds.attrs["source"].lower()
    assert "not an observation" in ds["sst"].attrs["long_name"].lower()


# --- retrieval ----------------------------------------------------------------------------------------------------------------------
def test_latest_timestamp_and_default_retrieval(prov):
    assert prov.latest_timestamp() == pd.Timestamp("2026-10-15")
    ds = prov.get_dataset()
    assert list(ds.time.values) == [np.datetime64("2026-10-15")]
    assert np.array_equal(prov.get_sst().values, ds["sst"].isel(time=0).values, equal_nan=True)
    assert len(prov.available_dates()) == 76 and prov.available_dates()[0] == pd.Timestamp("2026-08-01")


def test_requested_dates_and_ranges(prov):
    r = prov.get_dataset("2026-09-10", "2026-09-14")
    assert len(r.time) == 5 and pd.Timestamp(r.time.values[0]) == pd.Timestamp("2026-09-10")
    assert len(prov.get_dataset(end="2026-08-03").time) == 3                # start defaults to the first available day
    assert len(prov.get_dataset(start="2026-10-13").time) == 3              # end defaults to the latest
    assert len(prov.sst_series("2026-09-01", "2026-09-02").time) == 2
    both = prov.get_dataset("2026-09-10", "2026-09-10", ("sst", "climatology", "anomaly"))
    ok = prov.ocean_mask()
    assert np.allclose((both["climatology"] + both["anomaly"]).values[:, ok], both["sst"].values[:, ok], atol=1e-4)  # unless clipped at freezing


def test_unavailable_dates_and_bad_requests_are_explicit(prov):
    with pytest.raises(DateNotAvailable):
        prov.get_dataset("2026-10-16", "2026-10-17")
    with pytest.raises(DateNotAvailable):
        prov.get_sst("2020-01-01")
    with pytest.raises(ValueError):
        prov.get_dataset("2026-09-10", "2026-09-01")
    with pytest.raises(ValueError):
        prov.get_dataset(variables=("salinity",))
    with pytest.raises(ValueError):
        prov.get_dataset(lon_convention="90")


def test_oversized_requests_are_refused_instead_of_exhausting_memory():
    big = make(res=0.25, start="2012-01-01")      # 380k cells x 5,000+ days
    with pytest.raises(ValueError, match="shorter date range"):
        big.get_dataset("2012-01-01", "2026-10-15")


def test_longitude_convention_180_returns_wrapped_sorted_axis(prov):
    ds180 = prov.get_dataset(lon_convention="180")
    assert float(ds180.lon.min()) >= -180 and float(ds180.lon.max()) <= 180 and np.all(np.diff(ds180.lon.values) > 0)
    ds360 = prov.get_dataset()
    assert np.nansum(ds180["sst"].values) == pytest.approx(np.nansum(ds360["sst"].values), rel=1e-5)   # same data, re-ordered


# --- architecture -------------------------------------------------------------------------------------------------------------------
def test_provider_boundary_allows_replacement():
    class FakeRealProvider(EnvironmentalDataProvider):
        """Stands in for a future real provider: only the interface is implemented."""
        def metadata(self):
            return ProviderMetadata("fake_real", "observational", True, "d", "sst", {}, "degree_C", {}, "", "", 1.0, "1D", {}, "2026-01-01", (1, 1), 1, 1, "x")
        def grid(self): return np.array([0.5]), np.array([180.5])
        def ocean_mask(self): return np.ones((1, 1), bool)
        def available_dates(self): return pd.date_range("2026-01-01", "2026-01-03")
        def get_dataset(self, start=None, end=None, variables=("sst",), lon_convention="360"):
            import xarray as xr
            return xr.Dataset({"sst": (("time", "lat", "lon"), np.full((1, 1, 1), 20.0, "float32"))}, coords={"time": [np.datetime64("2026-01-03")], "lat": [0.5], "lon": [180.5]})

    def consumer(p: EnvironmentalDataProvider) -> float:        # downstream code sees only the interface
        return float(np.nanmean(p.get_sst().values)), p.latest_timestamp()

    assert consumer(FakeRealProvider())[0] == 20.0
    assert isinstance(consumer(make())[0], float)
    assert issubclass(TemporaryPacificProvider, EnvironmentalDataProvider)


def test_provider_needs_no_gpu_or_deep_learning_framework():
    code = "import sys, oceanmind_environment as e; p = e.build_from_cfg(__import__('oceanmind_preprocess.config', fromlist=['x']).load_config('config.yaml')); p.get_sst(); assert 'torch' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code], capture_output=True, text=True).returncode == 0
