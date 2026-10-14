"""NOAA OISST v2.1 ingestion (final + near-real-time) via ERDDAP griddap HTTPS NetCDF subsets.

Layout under paths.raw_dir:
  cache/<product>_<start>_<end>.nc (+ .json sidecar)   validated raw subsets, one per fetch batch
  sst_final.zarr / sst_nrt.zarr                        composed stores read by the preprocessing pipeline
  sst_manifest.parquet                                 per-date source / status / retrieval time

FINAL always wins over NRT for a date; NRT only supplies dates FINAL does not have yet.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd
import requests
import xarray as xr

log = logging.getLogger("oceanmind_preprocess")
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
STATUS = {"final": "final", "nrt": "preliminary"}


class IngestError(RuntimeError):
    pass


class NoDataError(IngestError):
    pass


class ValidationError(IngestError):
    pass


# ----------------------------------------------------------------------------- http
def _http(cfg):
    return cfg.ingest.http


def _get(url, cfg, stream=False):
    """GET with bounded exponential backoff on 5xx/429/timeouts. Raises NoDataError on 404, IngestError otherwise."""
    h = _http(cfg)
    last = None
    for attempt in range(1, h.max_retries + 1):
        wait = min(h.backoff_s * 2 ** (attempt - 1), h.max_backoff_s)
        try:
            r = requests.get(url, timeout=(15, h.timeout_s), stream=stream, headers={"User-Agent": "oceanmind-ingest/1.0"})
        except (requests.Timeout, requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as e:
            last = f"{type(e).__name__}: {e}"
        else:
            if r.status_code == 200:
                return r
            if r.status_code == 404:
                raise NoDataError(f"HTTP 404 (no matching data) for {_short(url)}: {r.text[:200]!r}")
            last = f"HTTP {r.status_code}: {r.text[:120]!r}"
            if r.status_code not in RETRY_STATUS:
                raise IngestError(f"{last} for {_short(url)}")
            ra = r.headers.get("Retry-After")
            if ra and ra.isdigit():
                wait = min(max(wait, int(ra)), h.max_backoff_s)
            r.close()
        if attempt < h.max_retries:
            log.warning("attempt %d/%d failed (%s); retrying in %.0fs", attempt, h.max_retries, last, wait)
            time.sleep(wait)
    raise IngestError(f"gave up after {h.max_retries} attempts on {_short(url)}: {last}. "
                      "Server or network unavailable; cached data is untouched. Re-run later.")


def _short(url):
    return url if len(url) < 160 else url[:157] + "..."


# ----------------------------------------------------------------------------- metadata
def _prod(cfg, product):
    p = cfg.ingest.sst.products[product]
    return p["host"].rstrip("/") + "/griddap/" + p["dataset"], p["dataset"]


def endpoint_info(cfg, product) -> dict:
    """Verify the live endpoint: variable, dimension order, units, and first/latest timestamps (from the server)."""
    base, ds_id = _prod(cfg, product)
    var = cfg.ingest.sst.var
    dds = _get(base + ".dds", cfg).text
    m = re.search(rf"Float32 {var}\[time = (\d+)\]\[zlev = (\d+)\]\[latitude = (\d+)\]\[longitude = (\d+)\]", dds)
    if not m:
        raise IngestError(f"{ds_id}: variable '{var}' with dims [time][zlev][latitude][longitude] not found in .dds:\n{dds[:600]}")
    das = _get(base + ".das", cfg).text
    blk = re.search(rf"\n\s*{var} \{{(.*?)\n\s*\}}", das, re.S)
    units = re.search(r'String units "([^"]*)"', blk.group(1)).group(1) if blk else None
    if units != cfg.ingest.sst.expected_units:
        raise IngestError(f"{ds_id}: sst units are {units!r}, expected {cfg.ingest.sst.expected_units!r}")

    def t(sel):
        txt = _get(base + ".csv?" + quote(f"time[{sel}]", safe=""), cfg).text
        return pd.Timestamp(pd.read_csv(StringIO(txt), skiprows=[1])["time"].iloc[0]).tz_localize(None)

    first, last = t("0"), t("(last)")
    return {"product": product, "dataset": ds_id, "n_time": int(m.group(1)), "units": units,
            "first": first.floor("D"), "latest": last.floor("D"), "latest_timestamp": last,
            "grid": f"{m.group(3)}x{m.group(4)} global 0.25deg"}


def server_days(cfg, product, t0, t1) -> pd.DatetimeIndex:
    """Days the server actually has in [t0, t1]. The OISST products have genuine gaps (a few days per year)."""
    base, _ = _prod(cfg, product)
    q = quote(f"time[({pd.Timestamp(t0):%Y-%m-%d}T12:00:00Z):1:({pd.Timestamp(t1):%Y-%m-%d}T12:00:00Z)]", safe="")
    try:
        txt = _get(f"{base}.csv?{q}", cfg).text
    except NoDataError:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.read_csv(StringIO(txt), skiprows=[1])["time"]).tz_localize(None).floor("D")


def subset_url(cfg, product, t0, t1) -> str:
    base, _ = _prod(cfg, product)
    g, var = cfg.grid, cfg.ingest.sst.var
    q = (f"{var}[({t0:%Y-%m-%d}T12:00:00Z):1:({t1:%Y-%m-%d}T12:00:00Z)][(0.0):1:(0.0)]"
         f"[({g.lat_min}):1:({g.lat_max})][({g.lon_min}):1:({g.lon_max})]")
    return f"{base}.nc?{quote(q, safe='')}"


# ----------------------------------------------------------------------------- validation
def validate_nc(path, cfg, expected=None) -> dict:
    """Open the file locally and check it is what we asked for. Raises ValidationError; returns a report."""
    s, g = cfg.ingest.sst, cfg.grid
    try:
        ds = xr.open_dataset(path)
        ds.load()
    except Exception as e:
        raise ValidationError(f"{Path(path).name}: not a readable NetCDF ({type(e).__name__}: {e})") from e
    try:
        if s.var not in ds.data_vars:
            raise ValidationError(f"variable '{s.var}' missing; have {list(ds.data_vars)}")
        da = ds[s.var]
        if da.dims != ("time", "zlev", "latitude", "longitude"):
            raise ValidationError(f"unexpected dimension order {da.dims}")
        if da.attrs.get("units") != s.expected_units:
            raise ValidationError(f"units {da.attrs.get('units')!r} != {s.expected_units!r}")
        times = pd.DatetimeIndex(ds.time.values)
        if times.has_duplicates:
            raise ValidationError("duplicate timestamps")
        if not times.is_monotonic_increasing:
            raise ValidationError("timestamps not increasing")
        days = times.floor("D")
        if expected is not None:  # exactly the days the server has for the requested range
            missing = expected.difference(days)
            if len(missing):
                raise ValidationError(f"{len(missing)} expected days missing, e.g. {missing[0].date()}")
            if len(days.difference(expected)):
                raise ValidationError("file contains days outside the requested range")
        half = cfg.grid.resolution / 2 + 1e-6
        lat, lon = ds.latitude.values, ds.longitude.values
        if lat.min() < g.lat_min - half or lat.max() > g.lat_max + half or lon.min() < g.lon_min - half or lon.max() > g.lon_max + half:
            raise ValidationError(f"coordinates outside configured region: lat {lat.min()}..{lat.max()}, lon {lon.min()}..{lon.max()}")
        v = da.values
        fin = np.isfinite(v)
        if not fin.any():
            raise ValidationError("all values are NaN")
        lo, hi = s.valid_range
        if v[fin].min() < lo or v[fin].max() > hi:
            raise ValidationError(f"SST outside plausible range {lo}..{hi}: {v[fin].min():.2f}..{v[fin].max():.2f}")
        return {
            "file": Path(path).name, "bytes": Path(path).stat().st_size, "variable": s.var, "dims": dict(da.sizes),
            "first": str(times[0]), "last": str(times[-1]), "n_times": len(times),
            "lat": [float(lat.min()), float(lat.max())], "lon": [float(lon.min()), float(lon.max())],
            "units": da.attrs["units"], "sst_min": float(v[fin].min()), "sst_max": float(v[fin].max()),
            "sst_mean": float(v[fin].mean()), "nan_fraction": float(1 - fin.mean()),
            "all_nan_days": int((~fin.reshape(len(times), -1).any(axis=1)).sum()),
        }
    finally:
        ds.close()


# ----------------------------------------------------------------------------- fetch
def paths(cfg):
    raw = Path(cfg.paths.raw_dir)
    cache = raw / cfg.ingest.cache_dir
    cache.mkdir(parents=True, exist_ok=True)
    return raw, cache


def fetch_range(cfg, product, t0, t1, name=None, expected=None) -> Path:
    """Download [t0, t1] (inclusive days) for the configured region, validate, then atomically publish into the cache.
    On any failure the existing cache is left untouched."""
    _, cache = paths(cfg)
    t0, t1 = pd.Timestamp(t0).floor("D"), pd.Timestamp(t1).floor("D")
    dest = cache / (name or f"{product}_{t0:%Y-%m-%d}_{t1:%Y-%m-%d}.nc")
    if expected is None:
        expected = server_days(cfg, product, t0, t1)
    if len(expected) == 0:
        raise NoDataError(f"{product}: server has no days in {t0.date()}..{t1.date()}")
    url = subset_url(cfg, product, t0, t1)
    part = dest.with_suffix(".nc.part")
    last = None
    for attempt in range(1, _http(cfg).max_retries + 1):
        r = _get(url, cfg, stream=True)
        n = 0
        try:
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
                    n += len(chunk)
            clen = r.headers.get("Content-Length")
            if clen and not r.headers.get("Content-Encoding") and int(clen) != n:
                raise ValidationError(f"incomplete download: {n} of {clen} bytes")
            report = validate_nc(part, cfg, expected)
        except (ValidationError, requests.RequestException) as e:
            last = e
            part.unlink(missing_ok=True)
            log.warning("download %s..%s invalid (%s); attempt %d", t0.date(), t1.date(), e, attempt)
            time.sleep(min(_http(cfg).backoff_s * 2 ** (attempt - 1), _http(cfg).max_backoff_s))
            continue
        finally:
            r.close()
        part.replace(dest)
        meta = {"product": product, "status": STATUS[product], "dataset": _prod(cfg, product)[1], "url": url,
                "retrieved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "http_status": 200, "report": report,
                "server_missing_days": [str(d.date()) for d in pd.date_range(t0, t1).difference(expected)]}
        dest.with_suffix(".json").write_text(json.dumps(meta, indent=2))
        return dest
    raise IngestError(f"could not obtain a valid file for {product} {t0.date()}..{t1.date()}: {last}")


def cached_dates(cfg, product) -> dict:
    """date -> cache file for all valid cached files (corrupt files are quarantined as .bad)."""
    _, cache = paths(cfg)
    out = {}
    for f in sorted(cache.glob(f"{product}_????-??-??_????-??-??.nc")):
        try:
            with xr.open_dataset(f) as ds:
                days = pd.DatetimeIndex(ds.time.values).floor("D")
        except Exception as e:
            log.warning("cache file %s unreadable (%s); quarantined", f.name, e)
            f.replace(f.with_suffix(".nc.bad"))
            continue
        for d in days:
            out[d] = f
    return out


def month_chunks(start, end, months=1):
    """Calendar-month-aligned batches of `months` months."""
    cur = pd.Timestamp(start).floor("D")
    end = pd.Timestamp(end).floor("D")
    while cur <= end:
        stop = cur + pd.offsets.MonthEnd(0)
        if months > 1:
            stop = stop + pd.offsets.MonthEnd(months - 1)
        stop = min(stop, end)
        yield cur, stop
        cur = stop + pd.Timedelta(days=1)


def fetch_period(cfg, product, start, end) -> dict:
    """Fill the cache for [start, end] in batches of ingest.batch_months, skipping days already cached."""
    have = cached_dates(cfg, product)
    done = skipped = 0
    for a, b in month_chunks(start, end, cfg.ingest.batch_months):
        want = server_days(cfg, product, a, b)  # server-side gaps are not "missing downloads"
        miss = [d for d in want if d not in have]
        if not miss:
            skipped += 1
            continue
        a2, b2 = min(miss), max(miss)  # only the span that is actually missing
        f = fetch_range(cfg, product, a2, b2, expected=want[(want >= a2) & (want <= b2)])
        done += 1
        log.info("%s: fetched %s..%s -> %s", product, a2.date(), b2.date(), f.name)
    return {"fetched_batches": done, "cached_batches": skipped}


# ----------------------------------------------------------------------------- compose
def _read_file(f, cfg):
    with xr.open_dataset(f) as ds:
        da = ds[cfg.ingest.sst.var].isel(zlev=0, drop=True).load()
    meta = json.loads(f.with_suffix(".json").read_text()) if f.with_suffix(".json").exists() else {}
    return da, meta


def _select(cfg, product, exclude_days=()):
    """Per-day latest-retrieved record from cache files -> (times, array, per-day meta rows, files contributing)."""
    _, cache = paths(cfg)
    items = []
    for f in sorted(cache.glob(f"{product}_????-??-??_????-??-??.nc")):
        try:
            da, meta = _read_file(f, cfg)
        except Exception:
            continue
        items.append((meta.get("retrieved_at", ""), f, da, meta))
    items.sort(key=lambda x: x[0])  # newest last -> wins
    chosen = {}
    for _, f, da, meta in items:
        for i, t in enumerate(pd.DatetimeIndex(da.time.values)):
            d = t.floor("D")
            if d in exclude_days:
                continue
            chosen[d] = (f, da, i, t, meta)
    if not chosen:
        return None
    days = sorted(chosen)
    ref = chosen[days[0]][1]
    arr = np.stack([chosen[d][1].isel(time=chosen[d][2]).values for d in days]).astype("float32")
    times = pd.DatetimeIndex([chosen[d][3] for d in days])
    rows = [{"date": d.strftime("%Y-%m-%d"), "obs_time_utc": chosen[d][3].isoformat(), "product": product,
             "status": STATUS[product], "dataset": chosen[d][4].get("dataset"), "source_url": chosen[d][4].get("url"),
             "retrieved_at": chosen[d][4].get("retrieved_at"), "file": chosen[d][0].name} for d in days]
    return times, arr, rows, {chosen[d][0] for d in days}, ref


def _write_store(cfg, product, times, arr, ref, path):
    ds = xr.Dataset({cfg.ingest.sst.var: (("time", "latitude", "longitude"), arr, {"units": cfg.ingest.sst.expected_units})},
                    coords={"time": times, "latitude": ref.latitude.values, "longitude": ref.longitude.values},
                    attrs={"source": _prod(cfg, product)[1], "status": STATUS[product], "composed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    tmp = Path(str(path) + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    ds.chunk({"time": 64}).to_zarr(tmp, mode="w")
    shutil.rmtree(path, ignore_errors=True)
    tmp.replace(path)


def compose(cfg) -> dict:
    """Rebuild sst_final.zarr, sst_nrt.zarr (NRT days not yet superseded by FINAL) and the manifest from the cache."""
    raw, cache = paths(cfg)
    store = cfg.raw.variables["sst"]["store"]
    fin = _select(cfg, "final")
    final_days = set() if fin is None else set(fin[0].floor("D"))
    nrt = _select(cfg, "nrt", exclude_days=final_days)
    rows, summary, used = [], {}, set()
    for product, sel in (("final", fin), ("nrt", nrt)):
        dst = raw / cfg.raw[f"{'final' if product == 'final' else 'nrt'}_pattern"].format(store=store)
        if sel is None:
            if product == "nrt" and dst.exists():
                shutil.rmtree(dst)  # every cached NRT day is now covered by FINAL
            summary[product] = None
            continue
        times, arr, r, files, ref = sel
        _write_store(cfg, product, times, arr, ref, dst)
        rows += r
        used |= files
        gaps = pd.date_range(times[0].floor("D"), times[-1].floor("D")).difference(times.floor("D"))
        summary[product] = {"first": str(times[0].date()), "last": str(times[-1].date()), "days": len(times),
                            "gap_days_in_source": [str(d.date()) for d in gaps], "store": str(dst)}
    pd.DataFrame(rows).to_parquet(raw / "sst_manifest.parquet", index=False)
    for f in cache.glob("*_????-??-??_????-??-??.nc"):  # prune cache files that no longer supply any day
        if f not in used and not f.name.startswith("smoke"):
            f.unlink()
            f.with_suffix(".json").unlink(missing_ok=True)
            log.info("pruned superseded cache file %s", f.name)
    return summary


# ----------------------------------------------------------------------------- modes
def _today():
    return pd.Timestamp(datetime.now(timezone.utc).date())


def describe(cfg, info_f, info_n):
    today = _today()
    print("NOAA OISST v2.1 (AVHRR-only, 0.25 deg daily)")
    for i in (info_f, info_n):
        if i:
            print(f"  {i['product']:<5} {i['dataset']}: {i['first'].date()} .. {i['latest'].date()} "
                  f"({(today - i['latest']).days} days behind today {today.date()}), units {i['units']}")
    print("  NRT is PRELIMINARY: ~1 day latency and may be revised; FINAL follows ~2 weeks later and replaces it.")


def mode_check(cfg):
    f = endpoint_info(cfg, "final")
    try:
        n = endpoint_info(cfg, "nrt")
    except IngestError as e:
        log.error("NRT endpoint unavailable: %s", e)
        n = None
    describe(cfg, f, n)
    return f, n


def mode_smoke(cfg, days=None, end=None) -> dict:
    """Small verified download of the FINAL product + a preprocessing probe on it. Does not touch the composed stores."""
    days = days or cfg.ingest.smoke_days
    info = endpoint_info(cfg, "final")
    end = pd.Timestamp(end) if end else info["latest"]
    start = end - pd.Timedelta(days=days - 1)
    if end > info["latest"] or start < info["first"]:
        raise IngestError(f"smoke period {start.date()}..{end.date()} outside {info['first'].date()}..{info['latest'].date()}")
    url = subset_url(cfg, "final", start, end)
    print(f"Region lat {cfg.grid.lat_min}..{cfg.grid.lat_max}, lon {cfg.grid.lon_min}..{cfg.grid.lon_max}; period {start.date()}..{end.date()}")
    print("GET", _short(url))
    f = fetch_range(cfg, "final", start, end, name=f"smoke_final_{start:%Y-%m-%d}_{end:%Y-%m-%d}.nc")
    meta = json.loads(f.with_suffix(".json").read_text())
    rep = meta["report"]
    print(f"HTTP {meta['http_status']}  file {f}  ({rep['bytes']:,} bytes)")
    for k in ("variable", "dims", "first", "last", "n_times", "lat", "lon", "units", "sst_min", "sst_max", "sst_mean", "nan_fraction", "all_nan_days"):
        print(f"  {k}: {rep[k]}")
    print("  duplicate timestamps: none; dimension order, units, bounds and value range validated")
    probe = preprocess_probe(cfg, f)
    print("Preprocessing probe:", probe)
    return {"report": rep, "probe": probe}


def preprocess_probe(cfg, nc_path) -> dict:
    """Push the downloaded file through the pipeline's alignment + land-mask code in a scratch raw dir."""
    from copy import deepcopy
    from .align import land_mask_from, load_aligned, make_grid
    from .config import Cfg
    with tempfile.TemporaryDirectory() as td:
        c = Cfg(deepcopy(dict(cfg)))
        c.paths.raw_dir = td
        with xr.open_dataset(nc_path) as ds:
            da = ds[cfg.ingest.sst.var].isel(zlev=0, drop=True).load()
        xr.Dataset({"sst": da}).to_zarr(Path(td) / cfg.raw.final_pattern.format(store=cfg.raw.variables["sst"]["store"]), mode="w")
        c.raw.variables = Cfg({"sst": c.raw.variables["sst"]})
        lat, lon = make_grid(c)
        al = load_aligned(c, lat, lon)
    land = land_mask_from(al.data["sst"])
    ocean = ~land
    vals = al.data["sst"][:, ocean]
    ok = bool(np.isfinite(vals).all()) and ocean.any() and land.any()
    if not ok:
        raise ValidationError("probe: after alignment, ocean cells contain NaN or the land mask is degenerate")
    return {"grid": f"{len(lat)}x{len(lon)}", "days": len(al.times), "ocean_cells": int(ocean.sum()), "land_cells": int(land.sum()),
            "ocean_nan": int(np.isnan(vals).sum()), "sst_range": [float(vals.min()), float(vals.max())]}


def mode_historical(cfg, start=None, end=None) -> dict:
    info = endpoint_info(cfg, "final")
    start = pd.Timestamp(start or cfg.ingest.history_start)
    end = pd.Timestamp(end or cfg.ingest.history_end or info["latest"])
    start, end = max(start, info["first"]), min(end, info["latest"])
    print(f"FINAL history {start.date()}..{end.date()} (server latest {info['latest'].date()})")
    res = fetch_period(cfg, "final", start, end)
    out = compose(cfg)
    print(res, out)
    return out


def mode_nrt(cfg, recent_days=None) -> dict:
    recent = recent_days or cfg.ingest.recent_days
    fi = endpoint_info(cfg, "final")
    ni = endpoint_info(cfg, "nrt")
    describe(cfg, fi, ni)
    have_final = cached_dates(cfg, "final")
    f_start = (max(have_final) + pd.Timedelta(days=1)) if have_final else fi["latest"] - pd.Timedelta(days=recent - 1)
    if f_start <= fi["latest"]:
        print(f"Catching up FINAL {f_start.date()}..{fi['latest'].date()}")
        fetch_period(cfg, "final", f_start, fi["latest"])
    # NRT: everything after the latest FINAL day, plus the configured recent window (re-fetched: preliminary values get revised)
    n_start = max(ni["first"], min(fi["latest"] + pd.Timedelta(days=1), ni["latest"] - pd.Timedelta(days=recent - 1)))
    if n_start <= ni["latest"]:
        print(f"Refreshing NRT {n_start.date()}..{ni['latest'].date()}")
        for a, b in month_chunks(n_start, ni["latest"]):
            fetch_range(cfg, "nrt", a, b)
    out = compose(cfg)
    print(out)
    return out


def mode_status(cfg):
    raw, _ = paths(cfg)
    m = raw / "sst_manifest.parquet"
    if not m.exists():
        print("no manifest yet; run historical/nrt first")
        return
    df = pd.read_parquet(m)
    for (p, s), g in df.groupby(["product", "status"]):
        print(f"{p:<5} {s:<11} {g.date.min()} .. {g.date.max()}  ({len(g)} days, retrieved {g.retrieved_at.min()} .. {g.retrieved_at.max()})")
    assert not df.date.duplicated().any(), "duplicate dates in manifest"


def main(argv=None):
    from .config import load_config
    ap = argparse.ArgumentParser(prog="download_sst", description="NOAA OISST v2.1 ingestion (final + near-real-time)")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("check", help="verify both ERDDAP endpoints and print latest available dates")
    s = sub.add_parser("smoke", help="small verified download + preprocessing probe")
    s.add_argument("--days", type=int)
    s.add_argument("--end")
    h = sub.add_parser("historical", help="download FINAL history in monthly batches (cached, resumable)")
    h.add_argument("--start")
    h.add_argument("--end")
    n = sub.add_parser("nrt", help="incremental update: new FINAL days + refreshed preliminary NRT window")
    n.add_argument("--recent-days", type=int)
    sub.add_parser("status", help="summarise the manifest")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    cfg = load_config(a.config)
    try:
        {"check": lambda: mode_check(cfg), "smoke": lambda: mode_smoke(cfg, a.days if a.mode == "smoke" else None, a.end if a.mode == "smoke" else None),
         "historical": lambda: mode_historical(cfg, getattr(a, "start", None), getattr(a, "end", None)),
         "nrt": lambda: mode_nrt(cfg, getattr(a, "recent_days", None)), "status": lambda: mode_status(cfg)}[a.mode]()
    except IngestError as e:
        print(f"\nINGEST FAILED: {e}", file=sys.stderr)
        return 1
    return 0
