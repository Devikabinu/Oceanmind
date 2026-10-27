"""Load raw Zarr stores, regrid to the common grid, and put them on a daily UTC-midnight axis."""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

log = logging.getLogger("oceanmind_preprocess")

_DIM_NAMES = {
    "time": ("time", "valid_time", "date"),
    "lat": ("lat", "latitude", "y", "nav_lat"),
    "lon": ("lon", "longitude", "x", "nav_lon"),
}
_DEPTH_NAMES = ("depth", "lev", "level", "z")


@dataclass
class Aligned:
    data: dict            # name -> float32 (T, H, W), NaN = missing/land
    times: pd.DatetimeIndex
    nrt: np.ndarray       # bool (T,): day uses NRT for at least one variable
    lat: np.ndarray
    lon: np.ndarray


def make_grid(cfg):
    g = cfg.grid
    res = g.resolution
    lat = np.round(g.lat_min + res * np.arange(int(round((g.lat_max - g.lat_min) / res)) + 1), 6)
    lon = np.round(g.lon_min + res * np.arange(int(round((g.lon_max - g.lon_min) / res)) + 1), 6)
    return lat, lon


def normalize_longitude(da: xr.DataArray, lon_start: float) -> xr.DataArray:
    """Put longitudes on the canonical axis: east-positive, strictly ascending and CONTINUOUS from `lon_start`.

    Every longitude is mapped into [lon_start, lon_start + 360). Values already inside that window are left exactly as they are, so a domain that does not
    cross the antimeridian (e.g. the NE Pacific, -160..-120) is unchanged whatever convention the source used (-180..180 or 0..360). A domain that does
    cross it (the Pacific, 100E..70W) gets labels above 180 (e.g. 179.5, 180.5, ..., 289.5) instead of being sorted into -180..180 with a gap, so
    neighbouring cells stay neighbours in the array. Convert back to -180..180 only for display (lon - 360 where lon > 180)."""
    lon = da.lon.values.astype("float64")
    outside = (lon < lon_start) | (lon >= lon_start + 360.0)
    if outside.any():
        lon = np.where(outside, lon_start + np.mod(lon - lon_start, 360.0), lon)
        da = da.assign_coords(lon=lon)
    da = da.sortby("lon")
    return da.isel(lon=~da.indexes["lon"].duplicated())      # e.g. a source that stores both -180 and 180


def _standardise(da: xr.DataArray, spec, lon_start: float | None = None) -> xr.DataArray:
    for std, cands in _DIM_NAMES.items():
        if std not in da.dims:
            for c in cands:
                if c in da.dims:
                    da = da.rename({c: std})
                    break
    for d in _DEPTH_NAMES:
        if d in da.dims:
            da = da.sel({d: spec.get("depth", 0.0)}, method="nearest", drop=True)
    for d in ("time", "lat", "lon"):
        if d not in da.dims:
            raise ValueError(f"variable has no {d} dimension (dims={da.dims})")
    if lon_start is not None:
        da = normalize_longitude(da, lon_start)
    elif float(da.lon.max()) > 180:  # legacy behaviour when no target domain is known: 0..360 -> -180..180
        da = da.assign_coords(lon=((da.lon + 180) % 360) - 180)
    da = da.sortby(["time", "lat", "lon"]).transpose("time", "lat", "lon")   # canonical: latitude ascending, longitude ascending
    if da.indexes["lat"].duplicated().any():
        raise ValueError("duplicate latitude rows in the source")
    return da


def _daily(da: xr.DataArray) -> xr.DataArray:
    """Timestamps are taken as UTC; floor to midnight and average sub-daily samples."""
    da = da.assign_coords(time=da.time.dt.floor("D"))
    return da.resample(time="1D").mean(skipna=True)


def _regrid_bilinear(da, lat, lon, min_weight):
    """NaN-aware bilinear: interpolate data and validity separately, so coasts are not eroded by NaNs."""
    valid = da.notnull().astype("float32")
    num = da.fillna(0).astype("float32").interp(lat=lat, lon=lon, method="linear")
    den = valid.interp(lat=lat, lon=lon, method="linear")
    return (num / den).where(den >= min_weight)


def _regrid_conservative(da, lat, lon):
    import xesmf as xe  # optional dependency

    def edges(c):
        mid = (c[1:] + c[:-1]) / 2
        return np.concatenate([[c[0] - (mid[0] - c[0])], mid, [c[-1] + (c[-1] - mid[-1])]])

    src = xr.Dataset({"lat": ("lat", da.lat.values), "lon": ("lon", da.lon.values),
                      "lat_b": ("lat_b", edges(da.lat.values)), "lon_b": ("lon_b", edges(da.lon.values))})
    dst = xr.Dataset({"lat": ("lat", lat), "lon": ("lon", lon),
                      "lat_b": ("lat_b", edges(lat)), "lon_b": ("lon_b", edges(lon))})
    return xe.Regridder(src, dst, "conservative_normed")(da)


def regrid(da, lat, lon, method="bilinear", min_weight=0.5):
    same = (da.sizes["lat"] == len(lat) and da.sizes["lon"] == len(lon)
            and np.allclose(da.lat.values, lat, atol=1e-4) and np.allclose(da.lon.values, lon, atol=1e-4))
    if same:  # source already on the target grid: no interpolation, NaNs untouched
        return da.assign_coords(lat=lat, lon=lon).astype("float32")
    if method == "conservative":
        try:
            return _regrid_conservative(da, lat, lon).astype("float32")
        except Exception as e:  # ImportError or xesmf failure
            log.warning("conservative regridding unavailable (%s); using bilinear", e)
    return _regrid_bilinear(da, lat, lon, min_weight).astype("float32")


def _open_one(cfg, name, path, lat, lon, t0, t1):
    path = Path(path)
    if not path.exists():
        return None
    spec = cfg.raw.variables[name]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ds = xr.open_zarr(path)
    pad = 1.0
    da = _standardise(ds[spec["var"]], spec, lon_start=float(lon.min()) - pad)
    da = da.sel(lat=slice(lat.min() - pad, lat.max() + pad), lon=slice(lon.min() - pad, lon.max() + pad))
    if t0 is not None or t1 is not None:
        end = None if t1 is None else pd.Timestamp(t1).floor("D") + pd.Timedelta(days=1) - pd.Timedelta(1, "ns")
        da = da.sel(time=slice(None if t0 is None else pd.Timestamp(t0).floor("D"), end))
    if da.sizes["time"] == 0:
        return None
    da = _apply_spec(da.load().astype("float32"), spec)
    da = _daily(da)
    return regrid(da, lat, lon, cfg.grid.regrid_method, cfg.grid.min_weight)


def _apply_spec(da: xr.DataArray, spec) -> xr.DataArray:
    """Unit conversion at the preprocessing boundary (value*scale + offset, optional log10). Identity for degC data."""
    da = da * spec.get("scale", 1.0) + spec.get("offset", 0.0)
    if spec.get("log10", False):
        da = np.log10(da.where(da > 0))  # values <= 0 are masked, not clipped
    return da


# ---------------------------------------------------------------------------------------------- environmental data providers
def source_is_provider(cfg, provider=None) -> bool:
    return provider is not None or cfg.raw.get("source", "stores") == "provider"


def validate_daily_axis(times: pd.DatetimeIndex, what: str = "provider") -> None:
    """A provider must deliver sorted, unique, UTC-midnight daily timestamps. Violations are rejected here instead of being silently averaged away."""
    if times.tz is not None:
        times = times.tz_convert("UTC").tz_localize(None)
    if not times.is_unique:
        raise ValueError(f"{what}: duplicate timestamps ({int(times.duplicated().sum())})")
    if not times.is_monotonic_increasing:
        raise ValueError(f"{what}: timestamps are not sorted ascending")
    if not (times == times.floor("D")).all():
        raise ValueError(f"{what}: timestamps are not at UTC midnight")


def _open_provider(cfg, provider, name, lat, lon, t0, t1):
    """DataArray[time,lat,lon] float32 on the target grid, from an EnvironmentalDataProvider, read in time chunks.
    Same contract as `_open_one`: latitude/longitude canonicalised, units converted per `raw.variables`, regridded only if the grids differ."""
    spec = cfg.raw.variables[name]
    var = spec["var"]
    meta = provider.metadata()
    if var not in meta.variables:
        raise KeyError(f"provider {meta.provider_id!r} does not supply variable {var!r} (it supplies {sorted(meta.variables)})")
    avail = pd.DatetimeIndex(provider.available_dates())
    validate_daily_axis(avail, f"provider {meta.provider_id!r} available_dates")
    s = avail[0] if t0 is None else max(avail[0], pd.Timestamp(t0).floor("D"))
    e = avail[-1] if t1 is None else min(avail[-1], pd.Timestamp(t1).floor("D"))
    days = avail[(avail >= s) & (avail <= e)]
    if len(days) == 0:
        return None
    pad = 1.0
    lon_start = float(lon.min()) - pad
    chunk = int(cfg.raw.get("provider_chunk_days", 366))
    parts = []
    for i in range(0, len(days), chunk):
        d0, d1 = days[i], days[min(i + chunk, len(days)) - 1]
        da = provider.get_dataset(d0, d1, (var,))[var]
        validate_daily_axis(pd.DatetimeIndex(da.time.values), f"provider {meta.provider_id!r} data")
        da = _standardise(da, spec, lon_start=lon_start)
        da = da.sel(lat=slice(lat.min() - pad, lat.max() + pad), lon=slice(lon.min() - pad, lon.max() + pad))
        da = _apply_spec(da.load().astype("float32"), spec)
        parts.append(regrid(da, lat, lon, cfg.grid.regrid_method, cfg.grid.min_weight))
    da = parts[0] if len(parts) == 1 else xr.concat(parts, "time")
    gaps = pd.date_range(days[0], days[-1], freq="D").difference(pd.DatetimeIndex(da.time.values))
    if len(gaps):
        log.warning("provider %r is missing %d day(s) in %s..%s (first: %s); they stay NaN, as for missing days in stored data",
                    meta.provider_id, len(gaps), days[0].date(), days[-1].date(), gaps[0].date())
    return da


def _load_variable_from_provider(cfg, name, lat, lon, t0, t1, provider):
    if provider is None:
        from oceanmind_environment import build_provider  # lazy: stores-based builds never import the provider package
        provider = build_provider(cfg)
    da = _open_provider(cfg, provider, name, lat, lon, t0, t1)
    if da is None:
        raise ValueError(f"no data for '{name}' in the requested period ({t0} .. {t1}) from provider {provider.metadata().provider_id!r}")
    return da, np.zeros(da.sizes["time"], bool)        # providers have no preliminary/NRT products


def load_variable(cfg, name, lat, lon, t0=None, t1=None, include_nrt=False, provider=None):
    """Return (DataArray[time,lat,lon], is_nrt bool array). FINAL wins; NRT only fills days FINAL lacks.
    With raw.source == 'provider' (or an explicit `provider`), data come from an EnvironmentalDataProvider instead of Zarr stores."""
    if source_is_provider(cfg, provider):
        return _load_variable_from_provider(cfg, name, lat, lon, t0, t1, provider)
    store = cfg.raw.variables[name]["store"]
    raw = Path(cfg.paths.raw_dir)
    final = _open_one(cfg, name, raw / cfg.raw.final_pattern.format(store=store), lat, lon, t0, t1)
    nrt = _open_one(cfg, name, raw / cfg.raw.nrt_pattern.format(store=store), lat, lon, t0, t1) if include_nrt else None
    if final is None and nrt is None:
        if not (raw / cfg.raw.final_pattern.format(store=store)).exists():
            raise FileNotFoundError(f"no FINAL store for '{name}' under {raw} (store={store})")
        raise ValueError(f"no data for '{name}' in the requested period ({t0} .. {t1})")
    if final is None:
        return nrt, np.ones(nrt.sizes["time"], bool)
    ok = final.notnull().any(("lat", "lon")).values
    final = final.isel(time=ok)
    if nrt is None:
        return final, np.zeros(final.sizes["time"], bool)
    has = nrt.notnull().any(("lat", "lon")).values & ~np.isin(nrt.time.values, final.time.values)
    nrt = nrt.isel(time=has)
    comb = xr.concat([final, nrt], "time").sortby("time")
    return comb, np.isin(comb.time.values, nrt.time.values)


def load_aligned(cfg, lat, lon, t0=None, t1=None, include_nrt=False, provider=None) -> Aligned:
    """All variables on one grid and a complete daily axis (missing days are NaN)."""
    loaded = {n: load_variable(cfg, n, lat, lon, t0, t1, include_nrt, provider) for n in cfg.raw.variables}
    ref = loaded[cfg.time.reference_var][0]
    t0 = pd.Timestamp(t0 if t0 is not None else ref.time.values[0]).floor("D")
    t1 = pd.Timestamp(t1 if t1 is not None else ref.time.values[-1]).floor("D")
    times = pd.date_range(t0, t1, freq="D")
    data, nrt = {}, np.zeros(len(times), bool)
    for n, (da, flag) in loaded.items():
        data[n] = da.reindex(time=times).values.astype("float32")
        nrt |= np.isin(times.values, da.time.values[flag])
    return Aligned(data, times, nrt, lat, lon)


def latest_available_date(cfg, include_nrt=True, provider=None) -> pd.Timestamp:
    if source_is_provider(cfg, provider):
        if provider is None:
            from oceanmind_environment import build_provider
            provider = build_provider(cfg)
        return pd.Timestamp(provider.latest_timestamp()).floor("D")
    spec = cfg.raw.variables[cfg.time.reference_var]
    pats = [cfg.raw.final_pattern] + ([cfg.raw.nrt_pattern] if include_nrt else [])
    best = None
    for pat in pats:
        p = Path(cfg.paths.raw_dir) / pat.format(store=spec["store"])
        if p.exists():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ds = xr.open_zarr(p)
            t = pd.Timestamp(ds[_first_time_name(ds)].values.max()).floor("D")
            best = t if best is None else max(best, t)
    if best is None:
        raise FileNotFoundError("no reference-variable store found")
    return best


def _first_time_name(ds):
    for n in _DIM_NAMES["time"]:
        if n in ds.coords:
            return n
    raise ValueError("no time coordinate")


def land_mask_from(ref: np.ndarray) -> np.ndarray:
    """True where the reference variable is NaN for the entire record (land). Never filled."""
    return np.isnan(ref).all(axis=0)
