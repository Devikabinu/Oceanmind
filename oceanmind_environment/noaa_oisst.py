"""NOAA OISST v2.1 as the Pacific environmental data provider (observational, daily, 0.25 degree source sampled onto a 1 degree grid).

Source data: NOAA/NCEI Optimum Interpolation SST v2.1 (Huang et al., 2021, J. Climate), served by the NOAA CoastWatch ERDDAP griddap service as the
"final" product (about two weeks behind real time) and the "preliminary"/near-real-time product (about two days behind). The final product always wins for
a day it covers. The Pacific crosses the antimeridian, so the data are requested as two longitude windows (100E..180 and 180..70W) and joined on one
contiguous east-longitude axis (100..290). Every fourth 0.25 degree cell is sampled in each direction, which gives the 1 degree analysis grid.

`sync()` downloads only what is missing (immutable final years/months are cached on disk and never fetched again; the changing tail is refreshed), validates
every file and writes one processed store. The provider then reads that store; nothing is fetched while the application runs.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import xarray as xr
from scipy import ndimage

from .base import DateNotAvailable, EnvironmentalDataProvider, ProviderMetadata
from .pacific_config import PacificDomainConfig
from .pacific_mask import NON_PACIFIC_BOXES

log = logging.getLogger("oceanmind.environment.noaa_oisst")

PROVIDER_ID = "noaa_oisst_v2_1_pacific"
VARIABLES = {"sst": {"units": "degree_C", "long_name": "Sea surface temperature (NOAA OISST v2.1)"}}
VALID_RANGE = (-3.0, 40.0)
STRIDE = 4                                     # 0.25 degree source -> 1 degree analysis grid
LAT_START, LON_START = -59.625, 100.375         # first sampled source cell centres; lon east of Greenwich
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
CITATION = "Huang, B., et al. (2021). Improvements of the Daily Optimum Interpolation Sea Surface Temperature (DOISST) Version 2.1. Journal of Climate, 34, 2923-2939."
PRODUCTS = {
    "final": {"server": "https://upwell.pfeg.noaa.gov/erddap/griddap", "dataset": "ncdcOisst21Agg_LonPM180",
              "label": "NOAA OISST v2.1 final (NOAA CoastWatch ERDDAP, ncdcOisst21Agg_LonPM180)"},
    "preliminary": {"server": "https://coastwatch.pfeg.noaa.gov/erddap/griddap", "dataset": "ncdcOisst21NrtAgg_LonPM180",
                    "label": "NOAA OISST v2.1 preliminary (NOAA CoastWatch ERDDAP, ncdcOisst21NrtAgg_LonPM180)"},
}


class SourceError(RuntimeError):
    pass


def _paths(cfg_dict: dict):
    base = Path(cfg_dict["config_path"]).parent
    s = cfg_dict["environment_provider"].get("source", {})
    cache = Path(s.get("cache_dir", "cache/pacific_oisst"))
    store = Path(s.get("store", "data/pacific_oisst/sst.zarr"))
    return (cache if cache.is_absolute() else base / cache), (store if store.is_absolute() else base / store)


def _get(url, timeout=(15, 300), retries=5, stream=False):
    last = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, timeout=timeout, stream=stream, headers={"User-Agent": "oceanmind-environment/1.0"})
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:120]!r}"
            r.close()
            if r.status_code not in RETRY_STATUS:
                raise SourceError(f"{last} for {url[:140]}")
        if attempt < retries:
            time.sleep(min(2 ** attempt, 60))
    raise SourceError(f"giving up after {retries} attempts ({last}) for {url[:140]}")


def server_days(product: str) -> pd.DatetimeIndex:
    p = PRODUCTS[product]
    r = _get(f"{p['server']}/{p['dataset']}.csv?time", timeout=(15, 120))
    t = pd.read_csv(StringIO(r.text), skiprows=[1])["time"]
    return pd.DatetimeIndex(pd.to_datetime(t, utc=True).dt.tz_localize(None).dt.floor("D"))


def _query(var, t0, t1, lat_end, lon0, lon1):
    from urllib.parse import quote
    q = (f"{var}[({t0:%Y-%m-%d}T12:00:00Z):1:({t1:%Y-%m-%d}T12:00:00Z)][(0.0):1:(0.0)]"
         f"[({LAT_START}):{STRIDE}:({lat_end})][({lon0}):{STRIDE}:({lon1})]")
    return quote(q, safe="")


def _lat_end(lat_max: float) -> float:
    return LAT_START + int((lat_max - LAT_START) // 1)


def _windows(lon_max: float):
    """Two LonPM180 request windows covering lon_min..lon_max east longitude across the antimeridian."""
    west_end = LON_START + int(179.9 - LON_START)                      # last sampled cell at or below 180
    east_start = west_end + 1.0 - 360.0
    east_end = LON_START + int((lon_max - LON_START) // 1) - 360.0
    return [(LON_START, west_end), (east_start, east_end)]


def _fetch_window(product, t0, t1, lat_end, lon0, lon1, dest: Path, expected: pd.DatetimeIndex):
    p = PRODUCTS[product]
    url = f"{p['server']}/{p['dataset']}.nc?{_query('sst', t0, t1, lat_end, lon0, lon1)}"
    part = dest.with_suffix(".part")
    last = None
    for attempt in range(1, 4):
        r = _get(url, stream=True)
        try:
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            _validate(part, expected)
        except (SourceError, OSError, ValueError, requests.RequestException) as e:
            last = e
            part.unlink(missing_ok=True)
            time.sleep(2 ** attempt)
            continue
        finally:
            r.close()
        part.replace(dest)
        dest.with_suffix(".json").write_text(json.dumps({"product": product, "dataset": p["dataset"], "url": url,
                                                         "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}, indent=1))
        return
    raise SourceError(f"could not obtain a valid file for {product} {t0.date()}..{t1.date()}: {last}")


def _validate(path: Path, expected: pd.DatetimeIndex):
    with xr.open_dataset(path) as ds:
        ds.load()
    if "sst" not in ds.data_vars:
        raise SourceError(f"{path.name}: variable 'sst' missing")
    da = ds["sst"]
    if da.dims != ("time", "zlev", "latitude", "longitude"):
        raise SourceError(f"{path.name}: unexpected dimensions {da.dims}")
    if da.attrs.get("units") != "degree_C":
        raise SourceError(f"{path.name}: unexpected units {da.attrs.get('units')!r}")
    times = pd.DatetimeIndex(ds.time.values).floor("D")
    if len(times) != len(expected) or (times != expected).any():
        raise SourceError(f"{path.name}: expected {len(expected)} days, got {len(times)}")
    v = da.values
    ok = np.isfinite(v)
    if not ok.any():
        raise SourceError(f"{path.name}: no valid ocean values")
    if v[ok].min() < VALID_RANGE[0] or v[ok].max() > VALID_RANGE[1]:
        raise SourceError(f"{path.name}: values outside {VALID_RANGE} (min {v[ok].min():.2f}, max {v[ok].max():.2f})")


def _chunks(start: pd.Timestamp, end: pd.Timestamp):
    """(first_day, last_day, complete) pieces: whole calendar years before the end year, calendar months within it. Only a piece that covers a whole
    year or month can be cached for good."""
    out, d = [], start
    while d <= end:
        y_end = pd.Timestamp(year=d.year, month=12, day=31)
        stop = min(y_end if d.year < end.year else d + pd.offsets.MonthEnd(0), end)
        whole_year = d == pd.Timestamp(year=d.year, month=1, day=1) and stop == y_end
        whole_month = d.day == 1 and stop == d + pd.offsets.MonthEnd(0)
        out.append((d, stop, whole_year or whole_month))
        d = stop + pd.Timedelta(days=1)
    return out


NCEI_DAILY = "https://www.ncei.noaa.gov/data/sea-surface-temperature-optimum-interpolation/v2.1/access/avhrr"


def _ncei_day(day: pd.Timestamp, lat_vals: np.ndarray, lon_vals: np.ndarray, cache: Path):
    """One day of NOAA OISST v2.1 from the NCEI archive (the source of the ERDDAP aggregation), sampled onto the analysis grid. Tries the final file, then the
    preliminary one. Returns (DataArray (lat, lon) in degC, is_preliminary) or None when NCEI has no file for that day."""
    for prelim in (False, True):
        name = f"oisst-avhrr-v02r01.{day:%Y%m%d}{'_preliminary' if prelim else ''}.nc"
        f = cache / f"ncei_{name}"
        if not f.exists():
            try:
                r = requests.get(f"{NCEI_DAILY}/{day:%Y%m}/{name}", timeout=(15, 120), headers={"User-Agent": "oceanmind-environment/1.0"})
            except requests.RequestException:
                continue
            if r.status_code != 200:
                continue
            part = f.with_suffix(".part")
            part.write_bytes(r.content)
            try:
                with xr.open_dataset(part) as ds:
                    sst = ds["sst"].isel(time=0, zlev=0)
                    sub = sst.sel(lat=lat_vals, lon=lon_vals).load()
                if sub.attrs.get("units") not in ("Celsius", "degree_C") or not np.isfinite(sub.values).any():
                    raise ValueError("unexpected content")
                v = sub.values
                if np.nanmin(v) < VALID_RANGE[0] or np.nanmax(v) > VALID_RANGE[1]:
                    raise ValueError("values out of range")
                sub.to_dataset(name="sst").to_netcdf(f)
            except (ValueError, KeyError, OSError):
                part.unlink(missing_ok=True)
                continue
            part.unlink(missing_ok=True)
        with xr.open_dataset(f) as ds:
            da = ds["sst"].load()
        return da.astype("float32"), prelim
    return None


def _forget_stale_downloads(cache: Path, used: set) -> None:
    """Delete downloaded pieces that this run no longer uses and that are not complete years or months: yesterday's open tail and the old preliminary range. Complete
    pieces are kept because they never change."""
    import re
    for f in list(cache.glob("*.nc")) + list(cache.glob("*.json")):
        m = re.match(r"(final|preliminary)_(\d{8})_(\d{8})_w\d\.(nc|json)$", f.name)
        if not m or (f.with_suffix(".nc") in used):
            continue
        a, b = pd.Timestamp(m.group(2)), pd.Timestamp(m.group(3))
        whole = (a.month == 1 and a.day == 1 and b.month == 12 and b.day == 31) or (a.day == 1 and b == a + pd.offsets.MonthEnd(0))
        if m.group(1) == "preliminary" or not whole:
            f.unlink(missing_ok=True)


def sync(cfg_dict: dict, force_tail: bool = True) -> dict:
    """Bring the processed store up to date with the NOAA servers. Returns a small report. Safe to re-run; cached immutable chunks are not downloaded again."""
    e = cfg_dict["environment_provider"]
    d, t = e["domain"], e["time"]
    cache, store = _paths(cfg_dict)
    cache.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(t["start"]).normalize()
    final_days, nrt_days = server_days("final"), server_days("preliminary")
    final_last, nrt_last = final_days[-1], nrt_days[-1]
    end = nrt_last
    lat_end = _lat_end(float(d["lat_max"]))
    windows = _windows(float(d["lon_max"]))
    log.info("NOAA OISST: final through %s, preliminary through %s", final_last.date(), nrt_last.date())
    downloaded = reused = 0

    def get_piece(product, a, b, immutable):
        nonlocal downloaded, reused
        expected_all = final_days if product == "final" else nrt_days
        expected = expected_all[(expected_all >= a) & (expected_all <= b)]
        files = []
        if len(expected) == 0:
            return files, expected
        qa, qb = expected[0], expected[-1]
        for k, (lon0, lon1) in enumerate(windows):
            f = cache / f"{product}_{a:%Y%m%d}_{b:%Y%m%d}_w{k}.nc"
            if immutable and f.exists():
                reused += 1
            else:
                _fetch_window(product, qa, qb, lat_end, lon0, lon1, f, expected)
                downloaded += 1
            files.append(f)
        return files, expected

    pieces = []                                              # (days, files)
    for a, b, complete in _chunks(start, final_last):
        files, days = get_piece("final", a, b, complete)
        pieces.append(("final", days, files))
    if nrt_last > final_last:
        files, days = get_piece("preliminary", final_last + pd.Timedelta(days=1), nrt_last, False)
        pieces.append(("preliminary", days, files))

    _forget_stale_downloads(cache, {f for _p, _d, files in pieces for f in files})
    arrays, flags, times = [], [], []
    for product, days, files in pieces:
        if not files:
            continue
        parts = []
        for f in files:
            with xr.open_dataset(f) as ds:
                da = ds["sst"].isel(zlev=0, drop=True).load()
            da = da.rename({"latitude": "lat", "longitude": "lon"})
            da = da.assign_coords(lon=(da.lon % 360).round(4), time=pd.DatetimeIndex(da.time.values).floor("D"))
            parts.append(da)
        da = xr.concat(parts, dim="lon").sortby("lon")
        arrays.append(da)
        times.append(da.time.values)
        flags.append(np.full(da.sizes["time"], product == "preliminary"))
    covered = pd.DatetimeIndex(np.concatenate(times)) if times else pd.DatetimeIndex([])
    gap_days = pd.date_range(start, nrt_last).difference(covered)
    lat_vals = LAT_START + np.arange(int((lat_end - LAT_START) // 1) + 1)
    lon_vals = np.round(LON_START + np.arange(int(float(d["lon_max"]) - LON_START) + 1), 4)
    filled, still_missing = [], []
    for gd in gap_days:
        got = _ncei_day(gd, lat_vals, lon_vals, cache)
        if got is None:
            still_missing.append(str(gd.date()))
            continue
        da, is_prelim = got
        da = da.expand_dims(time=[gd.to_datetime64()]).assign_coords(lat=lat_vals, lon=lon_vals)
        arrays.append(da)
        times.append(da.time.values)
        flags.append(np.full(1, bool(is_prelim) or gd > final_last))
        filled.append(str(gd.date()))
    if filled:
        log.info("%d day(s) missing from the ERDDAP aggregation were taken from the NCEI daily files: %s", len(filled), ", ".join(filled))
    if still_missing:
        log.warning("%d day(s) have no data in either source and stay missing: %s", len(still_missing), ", ".join(still_missing))
    sst = xr.concat(arrays, dim="time").astype("float32")
    prelim = np.concatenate(flags)
    sst = sst.assign_coords(preliminary=("time", prelim)).sortby("time")
    sst.name = "sst"
    sst.attrs = {"units": "degree_C", "long_name": VARIABLES["sst"]["long_name"]}
    ds_out = sst.to_dataset()
    ds_out.attrs.update(provider=PROVIDER_ID, citation=CITATION, final_through=str(final_last.date()), preliminary_through=str(nrt_last.date()),
                        synced_at=datetime.now(timezone.utc).isoformat(timespec="seconds"), stride=STRIDE,
                        source=" | ".join(PRODUCTS[k]["label"] for k in ("final", "preliminary")))
    ds_out = ds_out.chunk({"time": 366, "lat": ds_out.sizes["lat"], "lon": ds_out.sizes["lon"]})
    store.parent.mkdir(parents=True, exist_ok=True)
    tmp = store.with_name(store.name + ".tmp")
    if tmp.exists():
        import shutil
        shutil.rmtree(tmp)
    ds_out.to_zarr(tmp, mode="w")
    if store.exists():
        import shutil
        shutil.rmtree(store)
    tmp.rename(store)
    return {"days": int(sst.sizes["time"]), "first": str(pd.Timestamp(sst.time.values[0]).date()), "last": str(pd.Timestamp(sst.time.values[-1]).date()),
            "final_through": str(final_last.date()), "preliminary_through": str(nrt_last.date()), "gap_days_from_ncei": len(filled), "days_without_data": still_missing, "downloaded_files": downloaded, "cached_files": reused,
            "store": str(store)}


def _pacific_mask(lat, lon, valid_fraction):
    """Ocean cells that hold data in most of the record, in the Pacific water body (the largest connected ocean region once the Indian-Ocean openings
    are closed). Gulf of Mexico, Caribbean and other non-Pacific water inside the longitude window drop out because they are not connected to it."""
    ocean = valid_fraction >= 0.5
    LON, LAT = np.meshgrid(lon, lat)
    for (x0, y0, x1, y1) in NON_PACIFIC_BOXES.values():
        ocean = ocean & ~((LON >= x0) & (LON <= x1) & (LAT >= y0) & (LAT <= y1))
    labels, n = ndimage.label(ocean)
    if n == 0:
        return ocean
    sizes = ndimage.sum(ocean, labels, index=np.arange(1, n + 1))
    return labels == (1 + int(np.argmax(sizes)))


class NoaaOisstPacificProvider(EnvironmentalDataProvider):
    def __init__(self, config: PacificDomainConfig, store: Path, cfg_extra: dict | None = None):
        self.config = config
        if not Path(store).exists():
            raise FileNotFoundError(f"The processed NOAA OISST store {store} is missing. Run `python -m oceanmind_environment sync --config <config>` to download it.")
        self._ds = xr.open_zarr(store)
        self._lat = self._ds.lat.values.astype("float64")
        self._lon = self._ds.lon.values.astype("float64")
        self._dates = pd.DatetimeIndex(self._ds.time.values)
        self._prelim = np.asarray(self._ds["preliminary"].values, dtype=bool)
        self._attrs = dict(self._ds.attrs)
        mask_file = Path(store).parent / "ocean_mask.npy"
        if mask_file.exists() and np.load(mask_file).shape == (len(self._lat), len(self._lon)) and self._mask_current(mask_file):
            self._ocean = np.load(mask_file)
        else:
            vf = np.zeros((len(self._lat), len(self._lon)))
            idx = np.linspace(0, len(self._dates) - 1, min(len(self._dates), 400)).astype(int)
            vf = np.isfinite(self._ds["sst"].isel(time=idx).values).mean(axis=0)
            self._ocean = _pacific_mask(self._lat, self._lon, vf)
            np.save(mask_file, self._ocean)
            mask_file.with_suffix(".stamp").write_text(self._attrs.get("synced_at", ""))

    def _mask_current(self, f: Path) -> bool:
        s = f.with_suffix(".stamp")
        return s.exists() and s.read_text() == self._attrs.get("synced_at", "")

    def grid(self):
        return self._lat.copy(), self._lon.copy()

    def ocean_mask(self):
        return self._ocean.copy()

    def available_dates(self):
        return self._dates

    def metadata(self) -> ProviderMetadata:
        c = self.config
        h = c.resolution_deg / 2
        return ProviderMetadata(
            provider_id=PROVIDER_ID, provider_type="observational", is_observational=True,
            description="NOAA OISST v2.1: daily sea surface temperature analysis blending satellite and in-situ observations, sampled to a 1 degree Pacific grid.",
            dataset_type="sea_surface_temperature", variables=VARIABLES, units="degree_C",
            extent={"lat_min": float(self._lat[0] - h), "lat_max": float(self._lat[-1] + h), "lon_min": float(self._lon[0] - h), "lon_max": float(self._lon[-1] + h)},
            coordinate_system="geographic lat/lon degrees (WGS84), cell centres",
            lon_convention="east longitude 0..360 (contiguous across the antimeridian)",
            resolution_deg=c.resolution_deg, temporal_resolution=c.temporal_resolution,
            temporal_coverage={"start": str(self._dates[0].date()), "end": str(self._dates[-1].date()), "n_timestamps": int(len(self._dates))},
            latest_timestamp=str(self._dates[-1].date()), grid_shape=(len(self._lat), len(self._lon)), total_cells=int(self._ocean.size),
            valid_cells=int(self._ocean.sum()), mask_source="cells with SST in the NOAA OISST land-sea mask, Pacific water body",
            notes=["Sampled from the 0.25 degree OISST grid (every fourth cell) to a 1 degree analysis grid; coastal and small-scale features are not resolved.",
                   f"Final product through {self._attrs.get('final_through')}; the remaining days are preliminary and may change slightly when the final product is released."],
            source={"short_name": "NOAA OISST v2.1", "provider": "NOAA National Centers for Environmental Information (NCEI), distributed via NOAA CoastWatch ERDDAP",
                    "dataset": "NOAA Optimum Interpolation Sea Surface Temperature (OISST) v2.1, daily, 0.25 degree",
                    "urls": [f"{p['server']}/{p['dataset']}.html" for p in PRODUCTS.values()],
                    "reference_url": "https://www.ncei.noaa.gov/products/optimum-interpolation-sst", "citation": CITATION,
                    "final_through": self._attrs.get("final_through"), "preliminary_through": self._attrs.get("preliminary_through"),
                    "synced_at": self._attrs.get("synced_at"), "update_frequency": "daily (final product with about a two-week delay; preliminary about two days)"},
        )

    def preliminary_from(self):
        idx = np.flatnonzero(self._prelim)
        return str(self._dates[idx[0]].date()) if idx.size else None

    def get_dataset(self, start=None, end=None, variables=("sst",), lon_convention: str = "360") -> xr.Dataset:
        unknown = [v for v in variables if v not in VARIABLES]
        if unknown:
            raise ValueError(f"unknown variables {unknown}; available: {sorted(VARIABLES)}")
        if lon_convention not in ("360", "180"):
            raise ValueError("lon_convention must be '360' or '180'")
        first, last = self._dates[0], self._dates[-1]
        if start is None and end is None:
            s = e = last
        else:
            s = first if start is None else pd.Timestamp(start).normalize()
            e = last if end is None else pd.Timestamp(end).normalize()
        if s > e:
            raise ValueError("start must not be after end")
        if s < first or e > last:
            raise DateNotAvailable(f"requested {s.date()}..{e.date()} is outside the available coverage {first.date()}..{last.date()}")
        sub = self._ds["sst"].sel(time=slice(s, e)).load()
        sub = sub.where(xr.DataArray(self._ocean, dims=("lat", "lon")))
        ds = xr.Dataset({"sst": sub.reset_coords("preliminary", drop=True)}).assign_attrs(provider=PROVIDER_ID, is_observational=1, lon_convention="east longitude 0..360")
        if lon_convention == "180":
            ds = ds.assign_coords(lon=((ds.lon + 180) % 360) - 180).sortby("lon")
        return ds


def build_from_cfg(cfg, config: PacificDomainConfig) -> NoaaOisstPacificProvider:
    _, store = _paths(dict(cfg))
    return NoaaOisstPacificProvider(config, store)
