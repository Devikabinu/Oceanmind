"""Ingestion logic tested offline: the HTTP layer is replaced by a fake ERDDAP that serves synthetic NetCDF subsets."""
import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from oceanmind_preprocess import ingest
from oceanmind_preprocess.ingest import IngestError, ValidationError

from conftest import ROOT, make_cfg


class FakeResp:
    def __init__(self, status=200, content=b"", text="", headers=None):
        self.status_code, self.content, self.text, self.headers = status, content, text, headers or {}

    def iter_content(self, n):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass


def nc_bytes(cfg, t0, t1, offset=0.0, units="degree_C", tmp=None, gaps=()):
    g = cfg.grid
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    lat = np.arange(g.lat_min, g.lat_max + 1e-6, 0.25)
    lon = np.arange(g.lon_min, g.lon_max + 1e-6, 0.25)
    t = pd.DatetimeIndex([d for d in pd.date_range(t0, t1, freq="D") if str(d.date()) not in gaps]) + pd.Timedelta(hours=12)
    v = (15 + offset + np.zeros((len(t), 1, len(lat), len(lon)))).astype("float32")
    v[:, :, :2, :2] = np.nan
    ds = xr.Dataset({"sst": (("time", "zlev", "latitude", "longitude"), v, {"units": units})},
                    coords={"time": t, "zlev": [0.0], "latitude": lat, "longitude": lon})
    p = tmp / f"srv_{t0:%Y%m%d}_{t1:%Y%m%d}.nc"
    ds.to_netcdf(p)
    return p.read_bytes()


@pytest.fixture
def cfg(tmp_path):
    c = make_cfg(tmp_path, raw_dir=tmp_path / "raw")
    c.grid.update(lat_min=10.125, lat_max=11.875, lon_min=-150.875, lon_max=-149.125)
    c.ingest.batch_months = 1
    c.ingest.http.update(backoff_s=0.0, max_backoff_s=0.0, max_retries=3)
    return c


@pytest.fixture
def server(monkeypatch, cfg, tmp_path):
    """Fake server: FINAL has data up to LATEST_FINAL, NRT up to LATEST_NRT (with +0.5 offset = revised values)."""
    state = {"calls": [], "fail": [], "gaps": set(), "offset": {"final": 0.0, "nrt": 0.5}}

    def fake_get(url, timeout=None, stream=False, headers=None):
        state["calls"].append(url)
        if state["fail"]:
            f = state["fail"].pop(0)
            if isinstance(f, Exception):
                raise f
            return f
        from urllib.parse import unquote
        u = unquote(url)
        prod = "final" if "Agg_LonPM180" in u and "Nrt" not in u else "nrt"
        if u.endswith(".dds"):
            return FakeResp(text="Float32 sst[time = 10][zlev = 1][latitude = 720][longitude = 1440];")
        if u.endswith(".das"):
            return FakeResp(text='Attributes {\n  sst {\n    String units "degree_C";\n  }\n}\n')
        import re as _re
        mr = _re.search(r"\.csv\?time\[\((\d{4}-\d\d-\d\d)T12:00:00Z\):1:\((\d{4}-\d\d-\d\d)T12:00:00Z\)\]", u)
        if mr:
            days = [d for d in pd.date_range(mr.group(1), mr.group(2)) if str(d.date()) not in state["gaps"]]
            body = "\n".join(f"{d:%Y-%m-%d}T12:00:00Z" for d in days)
            return FakeResp(text="time\nUTC\n" + body + "\n")
        if ".csv?time" in u:
            latest = state["latest"][prod]
            ts = "2020-01-01T12:00:00Z" if "time[0]" in u else f"{latest}T12:00:00Z"
            return FakeResp(text=f"time\nUTC\n{ts}\n")
        import re
        m = re.search(r"\((\d{4}-\d\d-\d\d)T12:00:00Z\):1:\((\d{4}-\d\d-\d\d)T12:00:00Z\)", u)
        return FakeResp(content=nc_bytes(cfg, m.group(1), m.group(2), state["offset"][prod], tmp=tmp_path, gaps=state["gaps"]),
                        headers={})

    state["latest"] = {"final": "2021-03-20", "nrt": "2021-04-02"}
    monkeypatch.setattr(ingest.requests, "get", fake_get)
    monkeypatch.setattr(ingest.time, "sleep", lambda s: None)
    return state


def test_endpoint_info_and_latest_from_metadata(cfg, server):
    i = ingest.endpoint_info(cfg, "nrt")
    assert str(i["latest"].date()) == "2021-04-02" and i["units"] == "degree_C"


def test_wrong_units_rejected(cfg, server):
    cfg.ingest.sst.expected_units = "K"
    with pytest.raises(IngestError, match="units"):
        ingest.endpoint_info(cfg, "final")


def test_retry_on_503_then_success(cfg, server):
    server["fail"] = [FakeResp(503, text="unavailable"), ingest.requests.Timeout("slow")]
    f = ingest.fetch_range(cfg, "final", "2021-03-01", "2021-03-07")
    assert f.exists() and len(server["calls"]) == 4   # 2 failed + 1 ok time-axis query, then the .nc
    meta = json.loads(f.with_suffix(".json").read_text())
    assert meta["status"] == "final" and meta["report"]["n_times"] == 7


def test_gives_up_after_bounded_retries_and_keeps_cache(cfg, server):
    good = ingest.fetch_range(cfg, "final", "2021-03-01", "2021-03-07")
    before = good.read_bytes()
    server["fail"] = [FakeResp(503)] * 10
    with pytest.raises(IngestError, match="unavailable"):
        ingest.fetch_range(cfg, "final", "2021-03-01", "2021-03-07")
    assert good.read_bytes() == before                     # valid cache preserved


def test_404_is_not_retried(cfg, server):
    server["fail"] = [FakeResp(404, text="no matching results")]
    with pytest.raises(ingest.NoDataError):
        ingest.fetch_range(cfg, "final", "2021-03-01", "2021-03-02")
    assert len(server["calls"]) == 1


def test_incomplete_download_rejected_then_retried(cfg, server, tmp_path):
    full = nc_bytes(cfg, "2021-03-01", "2021-03-03", tmp=tmp_path)
    server["fail"] = [FakeResp(200, content=full[: len(full) // 2], headers={"Content-Length": str(len(full))})]
    f = ingest.fetch_range(cfg, "final", "2021-03-01", "2021-03-03", expected=pd.date_range("2021-03-01", "2021-03-03"))
    assert f.exists() and not f.with_suffix(".nc.part").exists()


def test_validation_catches_bad_files(cfg, tmp_path):
    p = tmp_path / "x.nc"
    p.write_bytes(b"not netcdf")
    with pytest.raises(ValidationError, match="readable"):
        ingest.validate_nc(p, cfg)
    p.write_bytes(nc_bytes(cfg, "2021-03-01", "2021-03-03", units="K", tmp=tmp_path))
    with pytest.raises(ValidationError, match="units"):
        ingest.validate_nc(p, cfg)
    p.write_bytes(nc_bytes(cfg, "2021-03-01", "2021-03-03", offset=100, tmp=tmp_path))
    with pytest.raises(ValidationError, match="plausible"):
        ingest.validate_nc(p, cfg)
    p.write_bytes(nc_bytes(cfg, "2021-03-01", "2021-03-03", tmp=tmp_path))
    with pytest.raises(ValidationError, match="missing"):
        ingest.validate_nc(p, cfg, pd.date_range("2021-03-01", "2021-03-05"))


def test_historical_is_cached_and_incremental(cfg, server):
    ingest.mode_historical(cfg, "2021-01-15", "2021-03-20")
    n = len([c for c in server["calls"] if ".nc?" in c])
    assert n == 3                                          # Jan, Feb, Mar batches
    ingest.mode_historical(cfg, "2021-01-15", "2021-03-20")
    assert len([c for c in server["calls"] if ".nc?" in c]) == n   # nothing re-downloaded
    z = xr.open_zarr(f"{cfg.paths.raw_dir}/sst_final.zarr").load()
    assert z.time.size == 65 and not pd.DatetimeIndex(z.time.values).has_duplicates


def test_nrt_update_final_supersedes_preliminary(cfg, server):
    ingest.mode_historical(cfg, "2021-03-01", "2021-03-20")
    ingest.mode_nrt(cfg, recent_days=5)
    raw = cfg.paths.raw_dir
    nrt = xr.open_zarr(f"{raw}/sst_nrt.zarr").load()
    assert str(nrt.time.values[0])[:10] == "2021-03-29" or pd.Timestamp(nrt.time.values[0]).date() >= pd.Timestamp("2021-03-21").date()
    assert pd.Timestamp(nrt.time.values[-1]).date() == pd.Timestamp("2021-04-02").date()
    man = pd.read_parquet(f"{raw}/sst_manifest.parquet")
    assert not man.date.duplicated().any()
    assert set(man[man["product"] == "nrt"].status) == {"preliminary"} and set(man[man["product"] == "final"].status) == {"final"}
    assert man.retrieved_at.notna().all() and man.obs_time_utc.notna().all()
    # FINAL catches up: previously-preliminary days become final, NRT store shrinks, no duplicates
    server["latest"]["final"] = "2021-03-31"
    ingest.mode_nrt(cfg, recent_days=5)
    man = pd.read_parquet(f"{raw}/sst_manifest.parquet")
    assert not man.date.duplicated().any()
    assert man[man.date == "2021-03-25"]["status"].iloc[0] == "final"
    assert man[man.date == "2021-04-01"]["status"].iloc[0] == "preliminary"
    fin = xr.open_zarr(f"{raw}/sst_final.zarr").load()
    assert float(fin.sst.sel(time="2021-03-25").mean()) == pytest.approx(15.0, abs=1e-3)   # final value, not NRT's +0.5


def test_nrt_failure_preserves_existing_stores(cfg, server):
    ingest.mode_historical(cfg, "2021-03-01", "2021-03-20")
    before = xr.open_zarr(f"{cfg.paths.raw_dir}/sst_final.zarr").load()
    server["latest"]["final"] = "2021-03-30"
    orig = ingest.fetch_range

    def boom(*a, **k):
        raise IngestError("simulated outage")
    ingest.fetch_range = boom
    try:
        with pytest.raises(IngestError):
            ingest.mode_nrt(cfg, recent_days=5)
    finally:
        ingest.fetch_range = orig
    after = xr.open_zarr(f"{cfg.paths.raw_dir}/sst_final.zarr").load()
    assert before.equals(after)


def test_stores_feed_the_preprocessing_pipeline(cfg, server):
    """FINAL+NRT stores written by ingestion load through the existing alignment code; NRT days are flagged."""
    from oceanmind_preprocess.align import load_aligned, make_grid
    from oceanmind_preprocess.config import load_config
    cfg.raw.variables = load_config(ROOT / "config.yaml").raw.variables   # the shipped SST-only mapping
    ingest.mode_historical(cfg, "2021-03-01", "2021-03-20")
    ingest.mode_nrt(cfg, recent_days=5)
    lat, lon = make_grid(cfg)
    al = load_aligned(cfg, lat, lon, include_nrt=True)
    assert al.data["sst"].shape[1:] == (len(lat), len(lon))
    assert al.nrt[:20].sum() == 0 and al.nrt[-1] and str(al.times[-1].date()) == "2021-04-02"


def test_server_side_gaps_are_accepted_recorded_and_not_refetched(cfg, server):
    server["gaps"] = {"2021-03-10"}
    ingest.mode_historical(cfg, "2021-03-01", "2021-03-20")
    n = len([c for c in server["calls"] if ".nc?" in c])
    z = xr.open_zarr(f"{cfg.paths.raw_dir}/sst_final.zarr").load()
    assert z.time.size == 19
    sidecar = next((__import__("pathlib").Path(cfg.paths.raw_dir) / "cache").glob("final_*.json"))
    assert json.loads(sidecar.read_text())["server_missing_days"] == ["2021-03-10"]
    ingest.mode_historical(cfg, "2021-03-01", "2021-03-20")
    assert len([c for c in server["calls"] if ".nc?" in c]) == n   # the gap day does not trigger a re-download
