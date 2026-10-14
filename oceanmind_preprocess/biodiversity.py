"""Grid OBIS occurrences onto the common grid: monthly species richness, record counts and sampling effort."""
from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr


def grid_obis(df: pd.DataFrame, cfg, lat, lon, ocean=None) -> pd.DataFrame:
    """Sparse table with one row per (month, cell) that has >=1 record.

    n_records        all records in the cell-month (also the sampling-effort proxy `effort`)
    n_species_records records identified to species
    richness         distinct species (raw, effort-biased -- model it with log_effort)
    n_sampling_days  distinct calendar days with a record; n_datasets distinct source datasets
    """
    c = cfg.biodiversity.columns
    res = cfg.grid.resolution
    d = pd.DataFrame({
        "lat": pd.to_numeric(df[c["lat"]], errors="coerce"),
        "lon": pd.to_numeric(df[c["lon"]], errors="coerce"),
        "date": pd.to_datetime(df[c["date"]], errors="coerce", utc=True).dt.tz_convert(None),
        "species": df[c["species"]] if c["species"] in df else None,
        "dataset": df[c["dataset"]] if c["dataset"] in df else None,
    }).dropna(subset=["lat", "lon", "date"])
    d["i"] = np.round((d.lat - lat[0]) / res).astype(int)
    d["j"] = np.round((d.lon - lon[0]) / res).astype(int)
    d = d[(d.i >= 0) & (d.i < len(lat)) & (d.j >= 0) & (d.j < len(lon))]
    if cfg.time.start is not None:
        d = d[d.date >= pd.Timestamp(cfg.time.start)]
    if cfg.time.end is not None:
        d = d[d.date < pd.Timestamp(cfg.time.end) + pd.Timedelta(days=1)]
    d["month"] = d.date.dt.to_period("M").dt.to_timestamp()
    d["day"] = d.date.dt.normalize()
    d["species"] = d["species"].replace("", np.nan)
    g = d.groupby(["month", "i", "j"]).agg(
        n_records=("lat", "size"),
        n_species_records=("species", "count"),
        richness=("species", "nunique"),
        n_sampling_days=("day", "nunique"),
        n_datasets=("dataset", "nunique"),
    ).reset_index()
    g["effort"] = g["n_records"].astype("float32")
    g["log_effort"] = np.log1p(g["n_records"]).astype("float32")
    g["lat"] = lat[g.i.to_numpy()]
    g["lon"] = lon[g.j.to_numpy()]
    g["ocean"] = True if ocean is None else ocean[g.i.to_numpy(), g.j.to_numpy()]
    return g.rename(columns={"i": "lat_idx", "j": "lon_idx"})


def to_dataset(tab: pd.DataFrame, lat, lon) -> xr.Dataset:
    """Dense monthly cube. Cells with no records have n_records=0 and NaN richness (unobserved, not zero)."""
    months = pd.date_range(tab.month.min(), tab.month.max(), freq="MS")
    shape = (len(months), len(lat), len(lon))
    m = months.get_indexer(pd.DatetimeIndex(tab.month))
    idx = (m, tab.lat_idx.to_numpy(), tab.lon_idx.to_numpy())
    out = {}
    for col, fill in (("n_records", 0), ("n_sampling_days", 0), ("effort", 0.0), ("richness", np.nan)):
        a = np.full(shape, fill, "float32")
        a[idx] = tab[col].to_numpy()
        out[col] = (("month", "lat", "lon"), a)
    return xr.Dataset(out, coords={"month": months, "lat": lat, "lon": lon})
