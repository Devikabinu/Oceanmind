"""Synthetic raw stores in the layout the pipeline expects (small grid, ~2.5 years)."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oceanmind_preprocess.config import load_config  # noqa: E402

FINAL_END = pd.Timestamp("2021-05-31")
NRT_START = pd.Timestamp("2021-05-20")
NRT_END = pd.Timestamp("2021-06-30")


def _field(times, lat, lon, kind, rng, nrt=False):
    doy = times.dayofyear.values[:, None, None]
    season = np.sin(2 * np.pi * (doy - 80) / 365.25)
    la = (lat - lat.min())[None, :, None]
    noise = rng.normal(0, 0.2, (len(times), len(lat), len(lon)))
    if kind == "sst":  # Kelvin
        a = 273.15 + 27 + 2 * season + 0.3 * la + noise
    elif kind == "sal":
        a = 34 + 0.5 * season + 0.1 * la + 0.1 * noise
    elif kind == "chl":
        a = 10 ** (-1 + 0.3 * season + 0.5 * noise)
    else:  # oxygen, with a depth axis (surface = first level)
        a = 200 + 10 * season + 5 * noise
    return (a + (0.5 if nrt else 0.0)).astype("float32")


def make_raw(raw_dir, perturb_from=None, seed=0):
    """Writes <store>_final.zarr (2019-01-01..2021-05-31, 0.5 deg grid, 12:00 stamps) and <store>_nrt.zarr."""
    rng = np.random.default_rng(seed)
    lat = np.arange(9.0, 14.01, 0.5)
    lon = np.arange(69.0, 76.01, 0.5)
    info = {}
    for store, var, kind in (("sst", "analysed_sst", "sst"), ("salinity", "so", "sal"),
                             ("chl", "chl", "chl"), ("oxygen", "o2", "oxy")):
        for nrt in (False, True):
            t = pd.date_range(NRT_START if nrt else "2019-01-01", NRT_END if nrt else FINAL_END, freq="D") + pd.Timedelta(hours=12)
            a = _field(t, lat, lon, kind, rng, nrt)
            a[:, 2:5, 2:4] = np.nan  # land block inside the target domain (source cells)
            if not nrt:
                cloud = rng.random(a.shape) < 0.04
                a[cloud] = np.nan
                # one cell with a 2-day gap (fillable) and one with a 6-day gap (not fillable)
                a[300:302, 6, 6] = np.nan
                a[300:306, 8, 8] = np.nan
                a[400:403, 5, 5] = np.nan
                a[400:403, 5, 6] = np.nan
                if kind == "chl":
                    a[10:13, 5, 5] = 0.0
                    a[20, 6, 6] = -1.0
                if perturb_from is not None and kind == "sst":
                    a[t >= perturb_from] += 8.0
            if kind == "oxy":
                a = np.stack([a, a + 50], axis=1)  # (time, depth, lat, lon)
                da = xr.DataArray(a, dims=("time", "depth", "latitude", "longitude"),
                                  coords={"time": t, "depth": [0.5, 10.0], "latitude": lat, "longitude": lon})
            else:
                da = xr.DataArray(a, dims=("time", "latitude", "longitude"),
                                  coords={"time": t, "latitude": lat, "longitude": lon})
            suffix = "nrt" if nrt else "final"
            da.to_dataset(name=var).to_zarr(Path(raw_dir) / f"{store}_{suffix}.zarr", mode="w")
    # OBIS occurrences
    n = 400
    obis = pd.DataFrame({
        "decimalLatitude": rng.uniform(9.9, 13.1, n),
        "decimalLongitude": rng.uniform(69.9, 74.9, n),
        "eventDate": pd.to_datetime("2019-06-01") + pd.to_timedelta(rng.integers(0, 700, n), unit="D"),
        "species": rng.choice(["a", "b", "c", "d", ""], n),
        "datasetID": rng.choice(["d1", "d2"], n),
    })
    (Path(raw_dir) / "obis").mkdir(exist_ok=True)
    obis.to_parquet(Path(raw_dir) / "obis" / "occurrences.parquet")
    return info


def make_cfg(tmp_path, raw_dir=None, out_dir=None):
    cfg = load_config(ROOT / "config.yaml")
    cfg.paths.raw_dir = str(raw_dir or tmp_path / "raw")
    cfg.paths.out_dir = str(out_dir or tmp_path / "out")
    cfg.grid.update(lat_min=10.0, lat_max=13.0, lon_min=70.0, lon_max=74.75)
    cfg.splits = type(cfg.splits)({"train": [None, "2020-12-31"], "val": ["2021-01-01", "2021-03-31"],
                                   "test": ["2021-04-01", None]})
    # The shipped config is SST-only (NOAA OISST). The synthetic stores exercise the full multi-variable path.
    V = type(cfg.raw.variables)
    cfg.raw.variables = V({
        "sst": {"store": "sst", "var": "analysed_sst", "scale": 1.0, "offset": -273.15, "log10": False},
        "sal": {"store": "salinity", "var": "so", "scale": 1.0, "offset": 0.0, "log10": False},
        "chl": {"store": "chl", "var": "chl", "scale": 1.0, "offset": 0.0, "log10": True},
        "oxy": {"store": "oxygen", "var": "o2", "scale": 1.0, "offset": 0.0, "log10": False, "depth": 0.0}})
    cfg.climatology.variables = ["sst", "sal", "chl", "oxy"]
    cfg.anomaly.channels = ["sst_anom", "sal", "chl", "oxy", "mask_sst", "mask_sal", "mask_chl", "mask_oxy"]
    cfg.anomaly.filter_vars = ["sst", "sal", "chl", "oxy"]
    cfg.anomaly.patch_size = [8, 8]
    cfg.anomaly.stride = 4
    return cfg


@pytest.fixture(scope="session")
def raw_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("raw")
    make_raw(d)
    return d


@pytest.fixture(scope="session")
def built(raw_dir, tmp_path_factory):
    from oceanmind_preprocess.pipeline import build
    cfg = make_cfg(None, raw_dir=raw_dir, out_dir=tmp_path_factory.mktemp("out"))
    summary = build(cfg)
    return cfg, summary
