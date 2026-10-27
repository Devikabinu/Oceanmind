"""Read access to PROCESSED environmental datasets (the output of `python -m oceanmind_preprocess build`) with region/bbox filtering and map-sized output.

Nothing here recomputes physics: SST and the SST anomaly are the channels the preprocessing pipeline already wrote (`sst`, `sst_anom`); this module only
de-normalises them with the pipeline's own stats.json, applies the pipeline's validity mask and slices/aggregates for the requested map view. Cubes are
memory-mapped and only the requested day is read, so a request never loads the multi-year record.

Datasets (central registry, see `dataset_refs`):
  ne_pacific  the original stored NOAA OISST study region (settings.PROCESSED_DIR)
  pacific     Pacific-wide data produced from the configured EnvironmentalDataProvider (settings.PROCESSED_PACIFIC_DIR)

Missing-data semantics: a cell is exactly one of  valid (0) | missing ocean (1) | land (2) | outside the requested region (3). Anything that is not valid is
NaN in the arrays and null in JSON; it is never turned into 0.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from app.core.config import get_settings
from app.services import geo_regions as geo
from app.services.environment import processed_dir

VALID, MISSING, LAND, OUTSIDE = 0, 1, 2, 3
LAYERS = {
    "sst": {"channel": "sst", "label": "Sea surface temperature", "unit": "degC", "diverging": False},
    "anomaly": {"channel": "sst_anom", "label": "SST anomaly (observed minus daily climatology)", "unit": "degC", "diverging": True},
}
SPLITS = ("train", "val", "test")


class DatasetError(Exception):
    pass


class UnknownDataset(DatasetError):
    pass


class DatasetUnavailable(DatasetError):
    pass


class UnknownLayer(DatasetError):
    pass


class NoDataForDate(DatasetError):
    def __init__(self, message, latest=None, first=None):
        super().__init__(message)
        self.latest, self.first = latest, first


@dataclass(frozen=True)
class DatasetRef:
    id: str
    name: str
    kind: str          # "stored" (NOAA OISST Zarr stores) | "provider" (EnvironmentalDataProvider)
    path: Path


def processed_pacific_dir() -> Path:
    configured = get_settings().PROCESSED_PACIFIC_DIR
    return Path(configured) if configured else Path(__file__).resolve().parents[3] / "processed_pacific"


def dataset_refs() -> dict[str, DatasetRef]:
    return {r.id: r for r in (
        DatasetRef("ne_pacific", "NE Pacific study region (stored NOAA OISST, processed)", "stored", processed_dir()),
        DatasetRef("pacific", "Pacific Ocean (basin-wide analysis)", "provider", processed_pacific_dir()),
    )}


def default_dataset_id() -> str:
    return get_settings().ENVIRONMENT_DEFAULT_DATASET


def resolve_dataset_id(dataset: str | None) -> str:
    ds = dataset or default_dataset_id()
    if ds not in dataset_refs():
        raise UnknownDataset(f"unknown dataset {ds!r}; valid datasets: {', '.join(dataset_refs())}")
    return ds


_LEGACY_SOURCE = {
    "provider_id": "noaa_oisst_v2.1_processed",
    "provider_type": "observational",
    "is_observational": True,
    "description": "NOAA OISST v2.1 daily SST, processed to the project's study-region grid.",
    "source": {"short_name": "NOAA OISST v2.1", "provider": "NOAA National Centers for Environmental Information (NCEI), distributed via NOAA CoastWatch ERDDAP",
               "dataset": "NOAA Optimum Interpolation Sea Surface Temperature (OISST) v2.1, daily, 0.25 degree",
               "urls": ["https://upwell.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg_LonPM180.html", "https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21NrtAgg_LonPM180.html"],
               "reference_url": "https://www.ncei.noaa.gov/products/optimum-interpolation-sst",
               "citation": "Huang, B., et al. (2021). Improvements of the Daily Optimum Interpolation Sea Surface Temperature (DOISST) Version 2.1. Journal of Climate, 34, 2923-2939.",
               "update_frequency": "daily (final product with about a two-week delay; preliminary about two days)"},
    "notes": ["The study region is stored at the native 0.25 degree resolution; the Pacific Ocean dataset covers the whole basin at 1 degree."],
}


class EnvironmentalStore:
    """One processed dataset. Cheap to construct; arrays are memory-mapped."""

    def __init__(self, ref: DatasetRef):
        self.ref = ref
        d = ref.path
        if not (d / "meta.json").exists() or not (d / "stats.json").exists() or not (d / "land_mask.npy").exists():
            raise DatasetUnavailable(f"dataset {ref.id!r} has not been built: {d} has no processed output. "
                                     "Run the preprocessing build for this dataset (see docs/PLATFORM.md).")
        self.meta = json.loads((d / "meta.json").read_text())
        _stats = json.loads((d / "stats.json").read_text())
        self.stats = _stats["channels"]
        self.train_period = _stats.get("train_period")
        self.channels = list(self.meta["channels"])
        self.lat = np.asarray(self.meta["lat"], dtype="float64")
        self.lon = np.asarray(self.meta["lon"], dtype="float64")
        self.land = np.load(d / "land_mask.npy")
        self.res = float(self.meta["resolution"])
        self._cubes: dict = {}
        self._clim = None
        index = {}
        for sp in SPLITS:
            f = d / "cubes" / f"{sp}_dates.npy"
            if f.exists():
                for row, t in enumerate(pd.DatetimeIndex(np.load(f))):
                    index[t.normalize()] = (sp, row)
        if not index:
            raise DatasetUnavailable(f"dataset {ref.id!r} has no dated cubes under {d / 'cubes'}")
        self.dates = pd.DatetimeIndex(sorted(index))
        self._index = index

    # ------------------------------------------------------------------------------------------------------ description
    @property
    def source(self) -> dict:
        return self.meta.get("source") or _LEGACY_SOURCE

    @property
    def lon_convention(self) -> str:
        return self.meta.get("lon_convention") or "east longitude, -180..180 (the domain does not cross the antimeridian)"

    @property
    def extent(self) -> dict:
        h = self.res / 2
        return {"lat_min": float(self.lat.min() - h), "lat_max": float(self.lat.max() + h),
                "lon_min": float(self.lon.min() - h), "lon_max": float(self.lon.max() + h)}

    def historical_anomaly(self, i: int, j: int, t, value: float, window: int = 15, min_samples: int = 30):
        """Where today's anomaly stands among the same-season (+-window days) anomalies of this one cell on earlier days of the record: (percentile 0-100, n) or (None, n)
        when there are too few samples. Reads one cell through the memory-mapped cubes."""
        ch, mk = self.channels.index("sst_anom"), self.channels.index("mask_sst")
        st = self.stats["sst_anom"]
        vals = []
        for sp in SPLITS:
            f = self.ref.path / "cubes" / f"{sp}_dates.npy"
            if not f.exists():
                continue
            dts = pd.DatetimeIndex(np.load(f))
            near = np.abs(((dts.dayofyear.to_numpy() - t.dayofyear + 183) % 366) - 183) <= window
            idx = np.flatnonzero(near & np.asarray(dts < t))
            if idx.size == 0:
                continue
            cube = self._cube(sp)
            a = np.asarray(cube[idx, ch, i, j], dtype="float64") * st["std"] + st["mean"]
            ok = np.asarray(cube[idx, mk, i, j]) > 0.5
            vals.append(a[ok])
        v = np.concatenate(vals) if vals else np.array([])
        if v.size < min_samples:
            return None, int(v.size)
        return round(100.0 * float((v < value).mean()), 1), int(v.size)

    def _preliminary_from(self, src: dict):
        """First day that comes from the preliminary (not yet final) product, when the source reports it."""
        final = src.get("final_through")
        if not final:
            return None
        nxt = pd.Timestamp(final) + pd.Timedelta(days=1)
        return str(nxt.date()) if nxt <= self.dates[-1] else None

    def freshness(self) -> dict:
        """How old the newest observation is, in plain terms. Old data is never presented as current."""
        today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
        behind = int((today - self.dates[-1]).days)
        status = "current" if behind <= 3 else "delayed" if behind <= 14 else "stale"
        msg = {"current": f"Latest observation is {behind} day{'s' if behind != 1 else ''} old.",
               "delayed": f"Latest observation is {behind} days old; newer data have not been loaded yet.",
               "stale": f"Latest observation is {behind} days old. These results describe that date, not today."}[status]
        return {"days_behind": behind, "status": status, "message": msg, "observation_date": str(self.dates[-1].date())}

    def describe(self) -> dict:
        meta_file = self.ref.path / "meta.json"
        src = (self.source or {}).get("source") or {}
        return {
            "id": self.ref.id, "name": self.ref.name, "kind": self.ref.kind, "is_default": self.ref.id == default_dataset_id(),
            "provider": self.source, "extent": self.extent, "resolution_deg": self.res, "units": "degC",
            "lon_convention": self.lon_convention, "grid_shape": [len(self.lat), len(self.lon)],
            "total_cells": int(self.land.size), "valid_cells": int((~self.land).sum()),
            "latest_date": str(self.dates[-1].date()), "first_date": str(self.dates[0].date()), "n_dates": int(len(self.dates)),
            "layers": {k: {"label": v["label"], "unit": v["unit"]} for k, v in LAYERS.items()},
            "variable": "Sea surface temperature (daily mean, degC) and its anomaly",
            "temporal_resolution": "daily",
            "baseline": self.train_period,
            "climatology": ("Daily climatology: the mean of each calendar day over the baseline period, smoothed (computed once in preprocessing)." if self.train_period else None),
            "processing": "Aligned to the analysis grid, quality-controlled, land-masked; anomaly = SST minus the daily climatology (computed in preprocessing, not in the API).",
            "update_method": "Rebuilt by the preprocessing build; the latest date is read from the processed dataset, never assumed.",
            "freshness": self.freshness(),
            "processed_at": pd.Timestamp(meta_file.stat().st_mtime, unit="s", tz="UTC").isoformat(timespec="seconds"),
            "source_timestamp": src.get("synced_at"),
            "preliminary_from": self._preliminary_from(src),
            "limitations": list(self.source.get("notes") or []) or ["Coverage is limited to the analysis domain; land and missing cells carry no value."],
        }

    # ------------------------------------------------------------------------------------------------------ data
    def resolve_date(self, date) -> pd.Timestamp:
        if date in (None, "latest"):
            return self.dates[-1]
        try:
            t = pd.Timestamp(date).normalize()
        except (ValueError, TypeError):
            raise ValueError(f"invalid date {date!r}; use YYYY-MM-DD or 'latest'") from None
        if t not in self._index:
            raise NoDataForDate(f"no data for {t.date()} in dataset {self.ref.id!r}: available {self.dates[0].date()} to {self.dates[-1].date()}",
                                latest=str(self.dates[-1].date()), first=str(self.dates[0].date()))
        return t

    def _cube(self, split):
        if split not in self._cubes:
            self._cubes[split] = np.load(self.ref.path / "cubes" / f"{split}.npy", mmap_mode="r")
        return self._cubes[split]

    def _climatology_day(self, doy: int):
        """Finite-ness of the pipeline's climatology on a day of year (an anomaly is only meaningful where the climatology exists)."""
        if self._clim is None:
            import xarray as xr
            self._clim = xr.open_zarr(self.ref.path / "climatology.zarr")["sst"]
        return np.isfinite(self._clim.isel(dayofyear=doy - 1).values)

    def native_layer(self, layer: str, date) -> tuple[np.ndarray, np.ndarray, pd.Timestamp]:
        """(values float32 with NaN where not valid, status int8 grid, resolved date) on the full native grid for one day."""
        if layer not in LAYERS:
            raise UnknownLayer(f"unknown layer {layer!r}; valid layers: {', '.join(LAYERS)}")
        t = self.resolve_date(date)
        split, row = self._index[t]
        cube = self._cube(split)
        ch = self.channels.index(LAYERS[layer]["channel"])
        st = self.stats[LAYERS[layer]["channel"]]
        has_data = np.asarray(cube[row, self.channels.index("mask_sst")]) > 0.5          # pipeline validity: observed or short-gap filled
        raw = np.asarray(cube[row, ch], dtype="float32") * np.float32(st["std"]) + np.float32(st["mean"])
        valid = has_data & ~self.land
        if layer == "anomaly":
            valid &= self._climatology_day(int(t.dayofyear))
        status = np.where(self.land, LAND, np.where(valid, VALID, MISSING)).astype("int8")
        return np.where(valid, raw, np.nan).astype("float32"), status, t


@lru_cache(maxsize=8)
def _store_cached(ds_id: str, path: str, stamp: float) -> EnvironmentalStore:
    return EnvironmentalStore(dataset_refs()[ds_id])


def get_store(dataset: str | None = None) -> EnvironmentalStore:
    ds_id = resolve_dataset_id(dataset)
    ref = dataset_refs()[ds_id]
    meta = ref.path / "meta.json"
    if not meta.exists():
        raise DatasetUnavailable(f"dataset {ds_id!r} has not been built: {ref.path} has no processed output. Run the preprocessing build for this dataset.")
    return _store_cached(ds_id, str(ref.path), meta.stat().st_mtime)


def clear_cache() -> None:
    _store_cached.cache_clear()


def list_datasets() -> list[dict]:
    out = []
    for ds_id, ref in dataset_refs().items():
        try:
            out.append({**get_store(ds_id).describe(), "available": True})
        except DatasetUnavailable as exc:
            out.append({"id": ds_id, "name": ref.name, "kind": ref.kind, "is_default": ds_id == default_dataset_id(), "available": False, "message": str(exc)})
    return out


# ------------------------------------------------------------------------------------------------------------- selection and aggregation
def selection_mask(store: EnvironmentalStore, region_id: str | None, bbox: tuple | None) -> np.ndarray:
    region = geo.get_region(region_id or "pacific")
    mask = geo.region_mask(region, store.lat, store.lon)
    if bbox is not None:
        mask &= geo.box_mask(store.lat, store.lon, geo.bbox_boxes(*bbox))
    return mask


def coverage_stats(status: np.ndarray, mask: np.ndarray) -> dict:
    total = int(mask.sum())
    land = int(((status == LAND) & mask).sum())
    valid = int(((status == VALID) & mask).sum())
    ocean = total - land
    missing = ocean - valid
    pct = lambda a, b: None if b == 0 else round(100.0 * a / b, 2)  # noqa: E731
    return {"total_cells": total, "land_cells": land, "ocean_cells": ocean, "valid_cells": valid, "missing_cells": missing,
            "valid_pct_of_ocean": pct(valid, ocean), "valid_pct_of_region": pct(valid, total), "ocean_pct_of_region": pct(ocean, total)}


def _block_aggregate(values, status, lat, lon, f):
    """Mean over f x f blocks of the VALID cells (NaN-aware). A block is valid if any member is; else missing if any member is missing ocean; else land."""
    H, W = values.shape
    ph, pw = (-H) % f, (-W) % f
    v = np.pad(values, ((0, ph), (0, pw)), constant_values=np.nan).reshape((H + ph) // f, f, (W + pw) // f, f)
    s = np.pad(status, ((0, ph), (0, pw)), constant_values=OUTSIDE).reshape(v.shape)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            mean = np.nanmean(v, axis=(1, 3))
    any_valid, any_missing, any_land = (s == VALID).any(axis=(1, 3)), (s == MISSING).any(axis=(1, 3)), (s == LAND).any(axis=(1, 3))
    st = np.where(any_valid, VALID, np.where(any_missing, MISSING, np.where(any_land, LAND, OUTSIDE))).astype("int8")
    la = np.pad(lat, (0, ph), constant_values=np.nan).reshape(-1, f)
    lo = np.pad(lon, (0, pw), constant_values=np.nan).reshape(-1, f)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return mean.astype("float32"), st, np.nanmean(la, axis=1), np.nanmean(lo, axis=1)


def _jsonable(a: np.ndarray, digits: int = 2) -> list:
    return [[None if not math.isfinite(x) else round(float(x), digits) for x in row] for row in a]


def map_response(dataset: str | None, layer: str, date, region_id: str | None, bbox: tuple | None, max_cells: int, include_status: bool = False) -> dict:
    store = get_store(dataset)
    region = geo.get_region(region_id or "pacific")
    values, status, t = store.native_layer(layer, date)
    mask = selection_mask(store, region_id, bbox)
    cov = coverage_stats(status, mask)
    base = {
        "dataset": store.describe(), "layer": layer, "label": LAYERS[layer]["label"], "unit": LAYERS[layer]["unit"], "diverging": LAYERS[layer]["diverging"],
        "kind": "observed" if store.source.get("is_observational") else "generated",
        "requested_date": date or "latest", "date": str(t.date()), "latest_available_date": str(store.dates[-1].date()),
        "region": {"id": region.id, "name": region.name}, "bbox": None if bbox is None else dict(zip(("min_lat", "max_lat", "min_lon", "max_lon"), bbox)),
        "coverage": cov,
    }
    if not mask.any():
        return {**base, "status_legend": _LEGEND, "lat": [], "lon": [], "values": [], "min": None, "max": None, "downsample_factor": 1, "native_shape": [0, 0],
                "lon_convention": store.lon_convention,
                "message": f"The selected region does not overlap the {store.ref.id!r} dataset's coverage ({store.extent}); no environmental model data are available there."}
    rows = np.flatnonzero(mask.any(axis=1))
    rows = np.arange(rows.min(), rows.max() + 1)
    cols = np.flatnonzero(mask.any(axis=0))
    ordered = cols[np.argsort(geo.to_east(store.lon[cols]), kind="stable")]       # travel order east, stitched across the antimeridian if needed
    runs = geo.column_runs(mask.any(axis=0))
    lon_sel = store.lon[ordered]
    if not np.all(np.diff(lon_sel) > 0):                                            # a wrapped axis (-180..180) cut by the region: unwrap to a continuous axis
        lon_sel = geo.to_east(lon_sel)
        lon_note = "east longitude 0..360 (unwrapped so the region is continuous across the antimeridian)"
    else:
        lon_note = store.lon_convention
    sel = np.ix_(rows, ordered)
    v, s, m = values[sel].copy(), status[sel].copy(), mask[sel]
    v[~m] = np.nan
    s[~m] = OUTSIDE
    lat_sel = store.lat[rows]
    f = 1
    if v.size > max_cells:
        f = int(math.ceil(math.sqrt(v.size / max_cells)))
        v, s, lat_sel, lon_sel = _block_aggregate(v, s, lat_sel, lon_sel, f)
    finite = v[np.isfinite(v)]
    out = {**base, "status_legend": _LEGEND, "lat": [round(float(x), 4) for x in lat_sel], "lon": [round(float(x), 4) for x in lon_sel], "values": _jsonable(v),
           "min": round(float(finite.min()), 2) if finite.size else None, "max": round(float(finite.max()), 2) if finite.size else None,
           "downsample_factor": f, "native_shape": [int(len(rows)), int(len(ordered))], "lon_convention": lon_note, "slices": len(runs)}
    if include_status:
        out["status"] = s.tolist()
    if cov["valid_cells"] == 0:
        out["message"] = "The selected region overlaps the dataset but has no valid data for this date."
    return out


_LEGEND = {"0": "valid data", "1": "ocean cell with missing data", "2": "land", "3": "outside the requested region"}


def coverage_response(dataset: str | None, layer: str, date, region_id: str | None, bbox: tuple | None) -> dict:
    store = get_store(dataset)
    region = geo.get_region(region_id or "pacific")
    _, status, t = store.native_layer(layer, date)
    mask = selection_mask(store, region_id, bbox)
    return {"dataset": store.describe(), "layer": layer, "region": {"id": region.id, "name": region.name},
            "bbox": None if bbox is None else dict(zip(("min_lat", "max_lat", "min_lon", "max_lon"), bbox)),
            "requested_date": date or "latest", "date": str(t.date()), "latest_available_date": str(store.dates[-1].date()),
            "extent": store.extent, "coverage": coverage_stats(status, mask),
            "overlaps_dataset": bool(mask.any())}


# ------------------------------------------------------------------------------------------------------------- point query
def _axis_lon(store: EnvironmentalStore, lon: float) -> float:
    """The ONE place a requested longitude (any convention: -180..180, 0..360, ...) is placed on the dataset own continuous axis."""
    origin = float(store.lon[0]) - store.res / 2
    return origin + float(np.mod(lon - origin, 360.0))


def point_response(dataset: str | None, lat: float, lon: float, date, layer: str | None = None) -> dict:
    """Environmental values at one coordinate. Reads one grid cell (memory-mapped cube + one climatology cell), never a whole field.
    status: valid | land | missing (ocean cell without data that day) | outside_dataset. Values are None unless status is valid; never 0, never a neighbour."""
    if not (math.isfinite(lat) and -90 <= lat <= 90):
        raise ValueError("lat must be a number between -90 and 90")
    if not (math.isfinite(lon) and -360 <= lon <= 360):
        raise ValueError("lon must be a number between -360 and 360 (either -180..180 or 0..360)")
    if layer is not None and layer not in LAYERS:
        raise UnknownLayer(f"unknown layer {layer!r}; valid layers: {', '.join(LAYERS)}")
    s = get_store(dataset)
    t = s.resolve_date(date)
    h = s.res / 2
    ext = s.extent
    axis_lon = _axis_lon(s, lon)
    base = {"dataset": s.describe(), "query": {"lat": lat, "lon": lon}, "date": str(t.date()), "latest_available_date": str(s.dates[-1].date()),
            "unit": "degC", "layer": layer, "lon_convention": s.lon_convention, "coverage": ext,
            "provider": s.source, "kind": "observed" if s.source.get("is_observational") else "generated",
            "cell": None, "sst": None, "anomaly": None}
    if not (ext["lat_min"] <= lat <= ext["lat_max"] and axis_lon <= ext["lon_max"]):
        return {**base, "status": "outside_dataset", "in_coverage": False, "is_ocean": None,
                "message": f"This location is outside the {s.ref.id!r} dataset ({ext['lat_min']:g} to {ext['lat_max']:g} degrees N, "
                           f"{ext['lon_min']:g} to {ext['lon_max']:g} degrees E); no environmental data are available here."}
    i = min(int(math.floor((lat - ext["lat_min"]) / s.res)), len(s.lat) - 1)
    j = min(int(math.floor((axis_lon - ext["lon_min"]) / s.res)), len(s.lon) - 1)
    cell = {"lat": round(float(s.lat[i]), 4), "lon": round(float(s.lon[j]), 4), "lon_180": round(float(((s.lon[j] + 180) % 360) - 180), 4), "row": i, "col": j}
    base["cell"] = cell
    if bool(s.land[i, j]):
        return {**base, "status": "land", "in_coverage": True, "is_ocean": False, "message": "Land at this location: no sea surface data."}
    split, row = s._index[t]
    cube = s._cube(split)
    has_data = bool(cube[row, s.channels.index("mask_sst"), i, j] > 0.5)
    if not has_data:
        return {**base, "status": "missing", "in_coverage": True, "is_ocean": True,
                "message": f"This ocean cell has no data on {t.date()} in this dataset."}

    def denorm(name):
        st = s.stats[LAYERS[name]["channel"]]
        return float(cube[row, s.channels.index(LAYERS[name]["channel"]), i, j]) * st["std"] + st["mean"]

    sst = round(denorm("sst"), 2)
    anom = None
    if bool(s._climatology_cell(int(t.dayofyear), i, j)):
        anom = round(denorm("anomaly"), 2)
    out = {**base, "status": "valid", "in_coverage": True, "is_ocean": True, "sst": sst, "anomaly": anom, "message": None}
    if anom is None:
        out["message"] = "No climatology exists for this cell and day, so the anomaly is not available (SST is)."
    return out


def _climatology_cell(self, doy: int, i: int, j: int) -> bool:
    if self._clim is None:
        import xarray as xr
        self._clim = xr.open_zarr(self.ref.path / "climatology.zarr")["sst"]
    return bool(np.isfinite(self._clim.isel(dayofyear=doy - 1, lat=i, lon=j).values))


EnvironmentalStore._climatology_cell = _climatology_cell


def summary_response(dataset: str | None, layer: str, date, region_id: str | None) -> dict:
    """Area-weighted (cos latitude) mean, min and max of a layer over a region on a date, plus coverage and provenance."""
    store = get_store(dataset)
    region = geo.get_region(region_id or "pacific")
    values, status, t = store.native_layer(layer, date)
    mask = selection_mask(store, region_id, None)
    if not mask.any():
        raise ValueError("The region does not overlap this dataset")
    ok = mask & (status == VALID) & np.isfinite(values)
    w = np.cos(np.deg2rad(store.lat))[:, None] * np.ones((1, len(store.lon)))
    mean = float((values[ok] * w[ok]).sum() / w[ok].sum()) if ok.any() else None
    return {"dataset": store.describe(), "layer": layer, "label": LAYERS[layer]["label"], "unit": LAYERS[layer]["unit"], "region": {"id": region.id, "name": region.name},
            "date": str(t.date()), "latest_available_date": str(store.dates[-1].date()), "mean": None if mean is None else round(mean, 2),
            "min": round(float(values[ok].min()), 2) if ok.any() else None, "max": round(float(values[ok].max()), 2) if ok.any() else None,
            "coverage": coverage_stats(status, mask), "provider": store.source, "kind": "observed" if store.source.get("is_observational") else "generated",
            "weighting": "cos(latitude) area weighting over valid cells"}
