"""NOAA OISST Pacific provider: request windows across the antimeridian, download chunking, the Pacific water-body mask, reading the merged store and filling gap days from the NCEI
daily files. No network: the store and the NCEI file are built locally."""
import io

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_environment import DateNotAvailable, PacificDomainConfig
from oceanmind_environment import noaa_oisst as no

LAT = no.LAT_START + 60 + np.arange(10)                      # 0.375 .. 9.375: tropical Pacific, away from the Indian Ocean exclusion boxes
LON = no.LON_START + np.arange(0, 190)                      # 100.375 .. 289.375 east, one contiguous axis


def config(store) -> PacificDomainConfig:
    return PacificDomainConfig(provider="noaa_oisst_pacific", lat_min=0.0, lat_max=10.0, lon_min=100.0, lon_max=290.0, resolution_deg=1.0, temporal_resolution="1D",
                               start_date="2024-01-01", end_date="2024-01-01", seed=0, mask_source="x", store=str(store))


def make_store(path, days=6, prelim_from=4, hole=False):
    rng = np.random.default_rng(1)
    times = pd.date_range("2024-03-01", periods=days)
    sst = (20 + rng.normal(0, 0.1, (days, len(LAT), len(LON)))).astype("float32")
    sst[:, :, 20:30] = np.nan                               # land / no data columns inside the domain
    if hole:
        sst[:, 3:6, 100:105] = np.nan
    ds = xr.Dataset({"sst": (("time", "lat", "lon"), sst)}, coords={"time": times, "lat": LAT, "lon": LON, "preliminary": ("time", np.arange(days) >= prelim_from)})
    ds.attrs.update(final_through=str(times[prelim_from - 1].date()), preliminary_through=str(times[-1].date()), synced_at="2026-10-23T00:00:00+00:00")
    ds.to_zarr(path, mode="w")
    return path


def test_request_windows_split_at_the_antimeridian_and_cover_the_domain_without_overlap():
    w, e = no._windows(290.0)
    assert w == (100.375, 179.375) and e == (-179.625, -70.625)
    west_n = int((w[1] - w[0]) / 1.0) + 1
    east_n = int((e[1] - e[0]) / 1.0) + 1
    assert west_n + east_n == 190                                   # 80 + 110 cells = the whole 100E-70W domain, each cell once
    assert (e[0] % 360) - w[1] == 1.0                                # the first east cell follows the last west cell by one grid step: no gap, no duplicate
    assert no._lat_end(65.0) == 64.375 and no._lat_end(-50.0) == -50.625


def test_downloads_are_cut_into_cacheable_years_and_months():
    chunks = no._chunks(pd.Timestamp("2022-06-01"), pd.Timestamp("2024-03-10"))
    assert [(a.date().isoformat(), b.date().isoformat(), whole) for a, b, whole in chunks][:3] == [
        ("2022-06-01", "2022-12-31", False), ("2023-01-01", "2023-12-31", True), ("2024-01-01", "2024-01-31", True)]
    assert chunks[-1][2] is False and chunks[-1][1] == pd.Timestamp("2024-03-10")           # the open tail is never treated as final


def test_a_download_with_the_wrong_days_or_units_is_rejected(tmp_path):
    t = pd.date_range("2024-01-01", periods=3)
    good = xr.Dataset({"sst": (("time", "zlev", "latitude", "longitude"), np.full((3, 1, 2, 2), 20.0, "float32"), {"units": "degree_C"})},
                      coords={"time": t + pd.Timedelta(hours=12), "zlev": [0.0], "latitude": [0.0, 1.0], "longitude": [0.0, 1.0]})
    f = tmp_path / "ok.nc"
    good.to_netcdf(f)
    no._validate(f, t)                                              # exactly the expected days
    with pytest.raises(no.SourceError, match="expected 4 days, got 3"):
        no._validate(f, pd.date_range("2024-01-01", periods=4))
    bad_units = good.copy()
    bad_units["sst"].attrs["units"] = "K"
    g = tmp_path / "k.nc"
    bad_units.to_netcdf(g)
    with pytest.raises(no.SourceError, match="units"):
        no._validate(g, t)
    hot = good.copy(data=None)
    hot["sst"] = good["sst"] + 40
    h = tmp_path / "hot.nc"
    hot.to_netcdf(h)
    with pytest.raises(no.SourceError, match="outside"):
        no._validate(h, t)


def test_pacific_mask_keeps_the_largest_connected_water_body_and_drops_enclosed_water():
    lat = np.arange(12.5, 20.0, 1.0)
    lon = np.arange(100.5, 290.0, 1.0)
    valid = np.ones((len(lat), len(lon)))
    valid[:, 150:152] = 0                                           # a north-south barrier: a small enclosed sea to the east (a Gulf-of-Mexico-like pocket)
    m = no._pacific_mask(lat, lon, valid)
    assert m[:, :150].all() and not m[:, 150:].any()                  # only the big connected basin is kept


def test_cells_with_data_in_fewer_than_half_the_days_are_not_ocean():
    lat = np.arange(0.5, 5.0, 1.0)
    lon = np.arange(100.5, 110.0, 1.0)
    frac = np.ones((len(lat), len(lon)))
    frac[2, 3] = 0.4                                                # data on 40% of the sampled days only (sea ice, land fringe)
    assert not no._pacific_mask(lat, lon, frac)[2, 3]


def test_the_indian_ocean_opening_south_of_australia_is_not_pacific():
    lat = np.arange(-59.5, -38.0, 1.0)
    lon = np.arange(100.5, 160.0, 1.0)
    m = no._pacific_mask(lat, lon, np.ones((len(lat), len(lon))))
    assert not m[:, :46].any()                                      # 100E-146.5E south of 39S is Indian / Southern Ocean water
    assert m[:, 47:].any()                                          # east of 146.5E it is the Pacific


def test_provider_exposes_the_store_on_one_contiguous_axis_with_a_mask_and_provenance(tmp_path):
    store = make_store(tmp_path / "sst.zarr")
    p = no.NoaaOisstPacificProvider(config(store), store)
    lat, lon = p.grid()
    assert lat[0] == 0.375 and lon[0] == 100.375 and lon[-1] == 289.375 and np.all(np.diff(lon) == 1.0)
    assert lon[79] == 179.375 and lon[80] == 180.375                 # the date line is crossed without a gap or a jump back to -180
    mask = p.ocean_mask()
    assert mask.shape == (10, 190) and not mask[:, 20:30].any() and mask[:, 40].all()
    m = p.metadata()
    assert m.is_observational and m.provider_id == no.PROVIDER_ID and m.source["short_name"] == "NOAA OISST v2.1"
    assert m.source["final_through"] == "2024-03-04" and m.temporal_coverage == {"start": "2024-03-01", "end": "2024-03-06", "n_timestamps": 6}
    assert p.preliminary_from() == "2024-03-05" and "preliminary" in " ".join(m.notes)
    assert p.latest_timestamp() == pd.Timestamp("2024-03-06")


def test_get_dataset_returns_requested_days_masks_land_and_supports_both_longitude_conventions(tmp_path):
    store = make_store(tmp_path / "sst.zarr")
    p = no.NoaaOisstPacificProvider(config(store), store)
    ds = p.get_dataset("2024-03-02", "2024-03-04")
    assert ds.sst.dims == ("time", "lat", "lon") and ds.sizes["time"] == 3 and ds.attrs["is_observational"] == 1
    assert np.isnan(ds.sst.values[:, :, 20:30]).all()                # land stays NaN (missing is never zero)
    assert np.isfinite(ds.sst.values[:, :, 40]).all()
    latest = p.get_dataset()
    assert latest.sizes["time"] == 1 and str(latest.time.values[0])[:10] == "2024-03-06"
    d180 = p.get_dataset("2024-03-06", "2024-03-06", lon_convention="180")
    assert float(d180.lon.min()) > -180 and float(d180.lon.max()) < 180 and np.all(np.diff(d180.lon.values) > 0)
    with pytest.raises(DateNotAvailable):
        p.get_dataset("2024-02-01", "2024-03-02")
    with pytest.raises(ValueError):
        p.get_dataset(variables=("salinity",))


def test_a_missing_store_says_how_to_create_it(tmp_path):
    with pytest.raises(FileNotFoundError, match="sync"):
        no.NoaaOisstPacificProvider(config(tmp_path / "none.zarr"), tmp_path / "none.zarr")


def test_gap_days_are_filled_from_the_ncei_daily_file(tmp_path, monkeypatch):
    """The ERDDAP aggregation lacks some days; the NCEI archive file of the same product supplies them, sampled onto the same grid."""
    lat = np.arange(-89.875, 90, 0.25, dtype="float32")
    lon = np.arange(0.125, 360, 0.25, dtype="float32")
    sst = np.full((1, 1, len(lat), len(lon)), 15.0, dtype="float32")
    ds = xr.Dataset({"sst": (("time", "zlev", "lat", "lon"), sst, {"units": "Celsius"})}, coords={"time": [np.datetime64("2023-12-19T12:00")], "zlev": [0.0], "lat": lat, "lon": lon})
    buf = tmp_path / "global.nc"
    ds.to_netcdf(buf)
    payload = buf.read_bytes()

    class R:
        status_code = 200
        content = payload

    calls = []
    monkeypatch.setattr(no.requests, "get", lambda url, **k: calls.append(url) or R())
    lat_vals = no.LAT_START + np.arange(5)
    lon_vals = no.LON_START + np.arange(190)
    got = no._ncei_day(pd.Timestamp("2023-12-19"), lat_vals, lon_vals, tmp_path)
    assert got is not None
    da, prelim = got
    assert prelim is False and da.shape == (5, 190) and np.allclose(da.values, 15.0)
    assert calls[0].endswith("/202312/oisst-avhrr-v02r01.20231219.nc")
    again = no._ncei_day(pd.Timestamp("2023-12-19"), lat_vals, lon_vals, tmp_path)           # second call reads the cached file
    assert again is not None and len(calls) == 1


def test_a_day_without_any_ncei_file_stays_missing(tmp_path, monkeypatch):
    class R:
        status_code = 404
        content = b""

    monkeypatch.setattr(no.requests, "get", lambda url, **k: R())
    assert no._ncei_day(pd.Timestamp("2023-12-19"), no.LAT_START + np.arange(3), no.LON_START + np.arange(5), tmp_path) is None
    assert not list(tmp_path.glob("ncei_*"))                                                  # nothing is invented or cached for it
