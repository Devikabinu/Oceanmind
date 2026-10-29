"""Automatic refresh: discovering the newest observation day, the one-day lag, the forecast window that follows it, keeping the previous dataset when the source has nothing
newer or cannot be reached, and checking that every product refers to the same day. No network: stages and sources are replaced."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oceanmind_environment import noaa_oisst as no
from oceanmind_environment import refresh_status as rs
from oceanmind_environment import schedule as sc

ROOT = Path(__file__).resolve().parents[1]


# ---- date discovery and the one-day lag ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("now, expected", [("2026-10-28 09:30", "2026-10-27"), ("2026-10-29 00:05", "2026-10-28"), ("2027-01-01", "2026-12-31"), ("2028-03-01", "2028-02-29")])
def test_the_expected_newest_day_is_yesterday_and_advances_with_the_clock(now, expected):
    assert str(sc.expected_latest(now).date()) == expected


def test_the_newest_day_is_discovered_from_the_listings_not_fixed():
    final = pd.date_range("2026-01-01", "2026-10-08")
    nrt = pd.date_range("2026-05-01", "2026-10-22")
    assert str(sc.discover_latest(final, nrt).date()) == "2026-10-22"
    assert str(sc.discover_latest(final, pd.date_range("2026-05-01", "2026-10-27")).date()) == "2026-10-27"          # a newer day appears: it is picked up
    assert sc.discover_latest(final, None) == pd.Timestamp("2026-10-08")
    assert sc.discover_latest(pd.DatetimeIndex([]), None) is None


def test_lag_status_current_delayed_and_stale():
    assert sc.lag_status("2026-10-27", "2026-10-28 10:00") == {"latest": "2026-10-27", "expected": "2026-10-27", "behind_expected": 0, "status": "current", "lag_days": 1}
    assert sc.lag_status("2026-10-26", "2026-10-28")["status"] == "delayed" and sc.lag_status("2026-10-26", "2026-10-28")["behind_expected"] == 1
    s = sc.lag_status("2026-10-22", "2026-10-28")
    assert s["status"] == "stale" and s["behind_expected"] == 5
    assert sc.lag_status("2026-10-28", "2026-10-28")["behind_expected"] == 0                      # never negative


def test_forecast_starts_the_day_after_the_newest_observation_and_moves_with_it():
    assert sc.forecast_window("2026-10-27") == ["2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03"]
    assert sc.forecast_window("2026-10-28")[0] == "2026-10-29" and sc.forecast_window("2026-10-28")[-1] == "2026-11-04"
    assert sc.forecast_window("2026-12-29")[-1] == "2027-01-05"
    assert len(sc.forecast_window("2026-10-27", 3)) == 3


def test_an_incomplete_trailing_day_is_not_the_newest_valid_observation():
    t = pd.date_range("2026-10-20", periods=8)
    valid = np.array([16000, 16100, 15950, 16020, 16050, 16010, 120, 0])                          # the last two days arrived (nearly) empty
    kept, dropped = sc.trim_incomplete_tail(t, valid)
    assert dropped == 2 and str(kept[-1].date()) == "2026-10-25"
    kept, dropped = sc.trim_incomplete_tail(t, np.full(8, 16000))
    assert dropped == 0 and len(kept) == 8
    kept, dropped = sc.trim_incomplete_tail(t, np.array([16000, 0, 16000, 16000, 16000, 16000, 16000, 16000]))
    assert dropped == 0                                                                           # only the tail is trimmed: an interior gap is handled elsewhere


# ---- the source cannot be reached or has nothing newer ---------------------------------------------------------------------------------------
def _cfg(tmp_path, store):
    return {"config_path": str(tmp_path / "c.yaml"), "environment_provider": {"domain": {"lat_max": 65.0, "lon_max": 290.0}, "time": {"start": "2024-01-01"},
                                                                              "source": {"cache_dir": str(tmp_path / "cache"), "store": str(store)}}}


def _down(product):
    raise no.SourceError("Connection to upwell.pfeg.noaa.gov timed out")


def test_sync_raises_when_noaa_is_unreachable_and_there_is_no_stored_record(tmp_path, monkeypatch):
    monkeypatch.setattr(no, "server_days", _down)
    with pytest.raises(no.SourceError, match="no stored record to extend"):
        no.sync(_cfg(tmp_path, tmp_path / "none.zarr"))


def _ncei(published):
    """A stand-in for the NCEI daily file lookup: the days in `published` exist (as preliminary), every other day is not published yet."""
    def fn(day, lat_vals, lon_vals, cache):
        if str(day.date()) not in published:
            return None
        import xarray as xr
        return xr.DataArray(np.full((len(lat_vals), len(lon_vals)), 21.5, "float32"), dims=("lat", "lon"), coords={"lat": lat_vals, "lon": lon_vals}), True
    return fn


def test_when_erddap_is_down_the_days_after_the_stored_record_come_from_the_ncei_archive(tmp_path, monkeypatch):
    from test_noaa_oisst import make_store
    store = make_store(tmp_path / "sst.zarr")                                         # stored record: 2024-03-01 .. 2024-03-06
    monkeypatch.setattr(no, "server_days", _down)
    monkeypatch.setattr(no, "expected_latest", lambda now=None, lag_days=1: pd.Timestamp("2024-03-09"))
    monkeypatch.setattr(no, "_ncei_day", _ncei({"2024-03-07", "2024-03-08"}))         # 03-09 is not published yet
    out = no.sync(_cfg(tmp_path, store))
    assert out["updated"] is True and out["last"] == "2024-03-08" and out["appended_days"] == 2 and "NCEI archive" in out["source"]
    import xarray as xr
    with xr.open_zarr(store) as z:
        assert str(pd.Timestamp(z.time.values[-1]).date()) == "2024-03-08" and z.sizes["time"] == 8
        assert z.preliminary.values.tolist()[-2:] == [True, True] and z.attrs["final_through"] == "2024-03-04" and z.attrs["preliminary_through"] == "2024-03-08"
        assert float(z.sst.isel(time=-1).mean()) == pytest.approx(21.5)                       # the new days are the downloaded values, the old days are untouched
        assert np.isnan(z.sst.isel(time=0).values[:, 20:30]).all()


def test_nothing_published_after_the_stored_record_changes_nothing_and_reports_the_actual_latest_day(tmp_path, monkeypatch):
    from test_noaa_oisst import make_store
    store = make_store(tmp_path / "sst.zarr")
    monkeypatch.setattr(no, "server_days", _down)
    monkeypatch.setattr(no, "expected_latest", lambda now=None, lag_days=1: pd.Timestamp("2024-03-09"))
    monkeypatch.setattr(no, "_ncei_day", _ncei(set()))
    out = no.sync(_cfg(tmp_path, store))
    assert out["updated"] is False and out["latest"] == "2024-03-06" and out["reason"] == "no_newer_data" and out["behind_expected"] > 0
    import xarray as xr
    with xr.open_zarr(store) as z:
        assert z.sizes["time"] == 6


def test_a_source_that_offers_fewer_days_than_stored_does_not_replace_the_record(tmp_path):
    from test_noaa_oisst import make_store
    import xarray as xr
    store = make_store(tmp_path / "sst.zarr", days=6)
    shorter = make_store(tmp_path / "other.zarr", days=4)
    with xr.open_zarr(shorter) as z:
        sst = z.sst.load()
    out = no._publish(sst, store, {"provider": "x"})
    assert out["updated"] is False and out["reason"] == "source_older_than_stored" and out["latest"] == "2024-03-06"


def load_daily():
    spec = importlib.util.spec_from_file_location("daily_refresh", ROOT / "scripts" / "daily_refresh.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def processed_dir(root: Path, latest: str, forecast_from: str | None = None, hw_latest: str | None = None, cache_latest: str | None = None):
    """A minimal processed dataset whose products all end on `latest`."""
    (root / "cubes").mkdir(parents=True)
    (root / "model" / "dashboard").mkdir(parents=True)
    days = pd.date_range(pd.Timestamp(latest) - pd.Timedelta(days=9), latest)
    for name, part in (("train", days[:5]), ("val", days[5:7]), ("test", days[7:])):
        np.save(root / "cubes" / f"{name}_dates.npy", part.values)
    (root / "model" / "dashboard" / "heatwave.json").write_text(json.dumps({"latest_date": hw_latest or latest}))
    issued = forecast_from or latest
    (root / "model" / "dashboard" / "snapshot.json").write_text(json.dumps({"latest": {"observed_date": issued, "target_dates": sc.forecast_window(issued)}}))
    np.savez(root / "region_series.npz", dates=np.array(pd.date_range(pd.Timestamp(cache_latest or latest) - pd.Timedelta(days=9), cache_latest or latest).values, dtype="datetime64[D]"))
    return root


def test_consistency_when_every_product_ends_on_the_same_day(tmp_path):
    c = rs.check_consistency(processed_dir(tmp_path / "p", "2026-10-27"))
    assert c["consistent"] is True and c["latest"] == "2026-10-27" and c["forecast_dates"][0] == "2026-10-28" and c["forecast_dates"][-1] == "2026-11-03"
    assert set(c["products"]) >= {"processed_cubes", "heatwaves", "forecast_issued_from", "sst_history"}


def test_consistency_names_the_product_that_is_out_of_date(tmp_path):
    for kw, key in (({"hw_latest": "2026-10-22"}, "heatwaves"), ({"cache_latest": "2026-10-22"}, "sst_history"), ({"forecast_from": "2026-10-22"}, "forecast_issued_from")):
        c = rs.check_consistency(processed_dir(tmp_path / key, "2026-10-27", **kw))
        assert c["consistent"] is False and any(key in p and "2026-10-22" in p for p in c["problems"]), c


def test_a_missing_product_is_reported_not_ignored(tmp_path):
    p = processed_dir(tmp_path / "p", "2026-10-27")
    (p / "region_series.npz").unlink()
    c = rs.check_consistency(p)
    assert c["consistent"] is False and "sst_history is missing" in c["problems"]


def test_a_forecast_that_does_not_start_the_day_after_the_observation_is_flagged(tmp_path):
    p = processed_dir(tmp_path / "p", "2026-10-27")
    (p / "model" / "dashboard" / "snapshot.json").write_text(json.dumps({"latest": {"observed_date": "2026-10-27", "target_dates": sc.forecast_window("2026-10-26")}}))
    c = rs.check_consistency(p)
    assert c["consistent"] is False and any("expected to start the day after 2026-10-27" in x for x in c["problems"])


def test_status_file_round_trip(tmp_path):
    assert rs.read_status(tmp_path) is None
    rs.write_status(tmp_path, outcome="unchanged", latest_observation="2026-10-22")
    s = rs.read_status(tmp_path)
    assert s["outcome"] == "unchanged" and s["latest_observation"] == "2026-10-22" and s["attempted_at"].endswith("+00:00")


# ---- the daily run ---------------------------------------------------------------------------------------------------------------------------
class Harness:
    def __init__(self, tmp_path, monkeypatch, previous="2026-10-22"):
        self.m = load_daily()
        self.processed = processed_dir(tmp_path / "processed", previous)
        self.calls = []
        monkeypatch.setattr(self.m, "ROOT", tmp_path)
        monkeypatch.setattr(self.m, "store_path", lambda: (None, self.processed))
        monkeypatch.setattr(self.m, "stage", self.stage)
        self.sync_result = None
        self.after = None

    def stage(self, *args, cwd=None, capture=False):
        self.calls.append(args)
        if args[:3] == ("-m", "oceanmind_environment", "sync"):
            if self.sync_result is None:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="SourceError: giving up after 5 attempts (ConnectTimeout)")
            return subprocess.CompletedProcess(args, 0, stdout="log noise\n" + json.dumps(self.sync_result, indent=2), stderr="")
        if args[:2] == ("scripts/refresh_pacific.py", "--only") and args[2] == "build" and self.after:
            processed_dir_replace(self.processed, self.after)
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")


def processed_dir_replace(root: Path, latest: str):
    import shutil
    shutil.rmtree(root)
    processed_dir(root, latest)


def test_unreachable_source_keeps_the_previous_dataset_and_says_so(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    status = h.m.run()
    assert status["outcome"] == "source_unavailable" and status["latest_observation"] == "2026-10-22"
    assert "previous valid dataset is kept" in status["message"]
    assert [c for c in h.calls if c[0] == "scripts/refresh_pacific.py"] == []                       # nothing downstream is rebuilt
    assert rs.read_status(tmp_path)["outcome"] == "source_unavailable"


def test_nothing_newer_is_not_rebuilt_and_reports_the_actual_latest_date(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.sync_result = {"updated": True, "latest": "2026-10-22", "expected": "2026-10-27", "behind_expected": 5, "status": "stale"}
    status = h.m.run()
    assert status["outcome"] == "unchanged" and status["latest_observation"] == "2026-10-22" and status["behind_expected"] == 5
    assert "No newer observation is available yet" in status["message"] and "2026-10-27" in status["message"]
    assert [c for c in h.calls if c[0] == "scripts/refresh_pacific.py"] == []


def test_a_newer_observation_rebuilds_everything_and_the_forecast_starts_the_next_day(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.sync_result = {"updated": True, "latest": "2026-10-27", "expected": "2026-10-27", "behind_expected": 0, "status": "current"}
    h.after = "2026-10-27"
    status = h.m.run()
    assert status["outcome"] == "updated" and status["latest_observation"] == "2026-10-27" and status["consistent"] is True
    assert status["forecast_dates"][0] == "2026-10-28" and status["forecast_dates"][-1] == "2026-11-03" and status["previous_latest"] == "2026-10-22"
    assert [c[2] for c in h.calls if c[0] == "scripts/refresh_pacific.py"] == ["climate", "build", "alerts"]


def test_a_failed_stage_is_reported_and_the_products_are_checked(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    h.sync_result = {"updated": True, "latest": "2026-10-27", "expected": "2026-10-27", "behind_expected": 0, "status": "current"}
    real = h.stage
    h.stage = lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "boom") if a[:3] == ("scripts/refresh_pacific.py", "--only", "build") else real(*a, **k)
    monkeypatch.setattr(h.m, "stage", h.stage)
    status = h.m.run()
    assert status["outcome"] == "failed" and "build" in status["message"] and "in place has observations to 2026-10-22" in status["message"]
    assert status["latest_observation"] == "2026-10-22" and status["consistent"] is True                      # users still see the previously published, consistent generation


def test_a_second_run_while_one_is_active_does_nothing(tmp_path, monkeypatch):
    m = load_daily()
    monkeypatch.setattr(m, "LOCK", tmp_path / "refresh.lock")
    holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (tmp_path / "refresh.lock").write_text(str(holder.pid))
        assert m.lock_holder() == holder.pid and m.acquire_lock() is False                   # a live run holds the lock
    finally:
        holder.kill()
        holder.wait()
    assert m.lock_holder() is None and m.acquire_lock() is True                                # the holder died: the lock is stale and is taken over
    assert (tmp_path / "refresh.lock").read_text() == str(__import__("os").getpid())


def test_a_lock_left_by_a_killed_run_does_not_block_the_next_one(tmp_path, monkeypatch):
    """The scheduled task was once terminated mid-run and its lock file blocked every later run for hours."""
    m = load_daily()
    monkeypatch.setattr(m, "LOCK", tmp_path / "refresh.lock")
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / "refresh.lock").write_text(str(dead.pid))
    assert m.lock_holder() is None and m.acquire_lock() is True
    (tmp_path / "refresh.lock").write_text("not a pid")
    assert m.lock_holder() is None


def test_the_scheduler_script_registers_a_daily_task_that_runs_the_refresh():
    ps = (ROOT / "scripts" / "install_daily_task.ps1").read_text()
    assert "daily_refresh.py" in ps and "New-ScheduledTaskTrigger -Daily" in ps and "StartWhenAvailable" in ps and "-Remove" in ps
    assert sys.version_info >= (3, 9)


def test_products_that_disagree_trigger_a_rebuild_even_when_the_source_has_nothing_newer(tmp_path, monkeypatch):
    h = Harness(tmp_path, monkeypatch)
    (h.processed / "model" / "dashboard" / "heatwave.json").write_text(json.dumps({"latest_date": "2026-10-20"}))          # stale heatwave results
    h.sync_result = {"updated": True, "latest": "2026-10-22", "expected": "2026-10-27", "behind_expected": 5, "status": "stale"}
    h.after = "2026-10-22"
    status = h.m.run()
    assert status["outcome"] == "updated" and status["consistent"] is True
    assert [c[2] for c in h.calls if c[0] == "scripts/refresh_pacific.py"] == ["climate", "build", "alerts"]


def test_the_processed_dataset_not_the_downloaded_store_decides_whether_a_rebuild_is_due(tmp_path, monkeypatch):
    """The store was already extended by an earlier run, but the rebuild never finished: the next run must rebuild, not report 'unchanged'."""
    h = Harness(tmp_path, monkeypatch, previous="2026-10-22")
    h.sync_result = {"updated": True, "latest": "2026-10-26", "expected": "2026-10-27", "behind_expected": 1, "status": "delayed"}
    h.after = "2026-10-26"
    status = h.m.run()
    assert status["outcome"] == "updated" and status["latest_observation"] == "2026-10-26" and status["forecast_dates"][0] == "2026-10-27"


# ------------------------------------------------------------------------------------------------ validation and idempotence of what is published
def _record(tmp_path, days=6):
    from test_noaa_oisst import make_store
    import xarray as xr
    with xr.open_zarr(make_store(tmp_path / "rec.zarr", days=days)) as z:
        return z.sst.load()


def test_a_good_record_passes_validation_and_reports_what_was_checked(tmp_path):
    v = no.validate_record(_record(tmp_path))
    assert v["missing_days"] == 0 and "coordinate orientation" in v["checked"] and v["last"] == "2024-03-06"


def test_gap_days_are_counted_not_filled(tmp_path):
    sst = _record(tmp_path, days=6).isel(time=[0, 1, 2, 4, 5])
    assert no.validate_record(sst)["missing_days"] == 1


@pytest.mark.parametrize("mutate,message", [
    (lambda s: s.isel(time=[0, 1, 1, 2, 3, 4]), "duplicate timestamps"),
    (lambda s: s.isel(time=[1, 0, 2, 3, 4, 5]), "increasing order"),
    (lambda s: s.isel(lat=slice(None, None, -1)), "strictly ascending"),
    (lambda s: s.assign_coords(lon=s.lon - 400), "longitudes outside"),
    (lambda s: s.assign_coords(lat=s.lat + 100), "latitudes outside"),
    (lambda s: s + 80, "physical range"),
    (lambda s: s.where(s.time < s.time[-1]), "newest day has no valid"),
])
def test_bad_records_are_rejected_before_they_can_replace_the_store(tmp_path, mutate, message):
    with pytest.raises(no.SourceError, match=message):
        no.validate_record(mutate(_record(tmp_path)))


def test_publishing_the_same_record_twice_changes_nothing(tmp_path):
    from test_noaa_oisst import make_store
    import xarray as xr
    store = make_store(tmp_path / "sst.zarr", days=6)
    with xr.open_zarr(store) as z:
        sst = z.sst.load()
        before = z.sst.values.copy()
    first = no._publish(sst, store, {"provider": "x"})
    assert first["updated"] is False and first["reason"] == "unchanged" and first["latest"] == "2024-03-06"          # the same record: nothing is rewritten
    second = no._publish(sst, store, {"provider": "x"})
    assert second["updated"] is False and second["days"] == 6 and second["validation"]["missing_days"] == 0
    with xr.open_zarr(store) as z:
        assert z.sizes["time"] == 6 and np.array_equal(np.nan_to_num(z.sst.values), np.nan_to_num(before))
