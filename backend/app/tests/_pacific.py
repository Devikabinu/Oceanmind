"""A tiny synthetic *processed Pacific* directory (same layout as `python -m oceanmind_preprocess build` writes) for API tests. Test data only."""
import json

import numpy as np
import pandas as pd
import xarray as xr

LAT = np.arange(-58.0, 62.1, 4.0)          # 31 rows
LON = np.arange(102.0, 286.1, 4.0)         # 47 columns, continuous east longitude (crosses 180)
H, W = len(LAT), len(LON)
CHANNELS = ["sst", "sst_anom", "sst_grad", "doy_sin", "doy_cos", "mask_sst"]
SST_STAT, ANOM_STAT = (20.0, 5.0), (0.0, 1.0)
DATES = pd.date_range("2020-01-01", "2020-01-20")
LATEST = "2020-01-20"
MISSING_CELLS = [(5, c) for c in range(10, 15)]      # ocean cells with no data on the latest day only
NO_CLIM_CELL = (8, 20)                               # ocean cell whose climatology does not exist on day-of-year 20
PROVIDER = {"provider_id": "pacific_test_dataset", "provider_type": "modelled", "is_observational": False,
            "description": "Small modelled Pacific dataset used by the tests."}


def land_mask():
    la, lo = LAT[:, None], LON[None, :]
    return ((lo <= 130) & (la >= 20)) | ((lo >= 270) & (la >= -40))


def raw_fields(day: int):
    la, lo = LAT[:, None] * np.ones((1, W)), LON[None, :] * np.ones((H, 1))
    sst = 28.0 - 0.25 * np.abs(la) + 0.01 * day + 0.001 * (lo - 100)
    anom = 0.5 + 0.1 * ((np.arange(W)[None, :] % 3) - 1) + 0.01 * day + 0 * la
    return sst.astype("float32"), anom.astype("float32")


def build(root, source=PROVIDER, hot=None):
    """hot: ((row0, row1), (col0, col1), delta): extra anomaly (degC) on those cells on the latest day only."""
    (root / "cubes").mkdir(parents=True, exist_ok=True)
    land = land_mask()
    np.save(root / "land_mask.npy", land)
    splits = {"train": DATES[:10], "val": DATES[10:13], "test": DATES[13:]}
    for name, idx in splits.items():
        cube = np.zeros((len(idx), len(CHANNELS), H, W), dtype="float32")
        for k, t in enumerate(idx):
            day = (t - DATES[0]).days
            sst, anom = raw_fields(day)
            if hot and t == DATES[-1]:
                (r0, r1), (c0, c1), delta = hot
                anom = anom.copy()
                anom[r0:r1, c0:c1] += delta
            has = ~land
            if t == DATES[-1]:
                for r, c in MISSING_CELLS:
                    has[r, c] = False
            cube[k, 0] = np.where(has, (sst - SST_STAT[0]) / SST_STAT[1], 0)
            cube[k, 1] = np.where(has, (anom - ANOM_STAT[0]) / ANOM_STAT[1], 0)
            cube[k, 5] = has
        np.save(root / "cubes" / f"{name}.npy", cube)
        np.save(root / "cubes" / f"{name}_dates.npy", idx.values.astype("datetime64[ns]"))
    meta = {"lat": LAT.tolist(), "lon": LON.tolist(), "resolution": 4.0, "channels": CHANNELS,
            "lookback_days": 7, "horizons": list(range(1, 8)), "target_channel": "sst", "forecast_channels": ["sst", "sst_anom", "sst_grad", "doy_sin", "doy_cos", "mask_sst"],
            "splits": {"train": {"start": "2020-01-01", "end": "2020-01-12", "days": 12}, "val": {"start": "2020-01-13", "end": "2020-01-13", "days": 1},
                       "test": {"start": "2020-01-14", "end": "2020-01-20", "days": 7}}}
    if source:
        meta.update(source=source, lon_convention="east longitude, continuous (labels may exceed 180 for domains crossing the antimeridian)")
    (root / "meta.json").write_text(json.dumps(meta))
    (root / "stats.json").write_text(json.dumps({"channels": {"sst": {"mean": SST_STAT[0], "std": SST_STAT[1]},
                                                                "sst_anom": {"mean": ANOM_STAT[0], "std": ANOM_STAT[1]}}}))
    clim = np.full((366, H, W), 20.0, dtype="float32")
    clim[19, NO_CLIM_CELL[0], NO_CLIM_CELL[1]] = np.nan
    xr.Dataset({"sst": (("dayofyear", "lat", "lon"), clim)}, coords={"dayofyear": np.arange(1, 367), "lat": LAT, "lon": LON}).to_zarr(root / "climatology.zarr", mode="w")
    return root
