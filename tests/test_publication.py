"""Versioned publication of a refresh: the new generation is built beside the live dataset and swapped in whole; failures at any stage leave the live dataset untouched; an
interrupted swap is repaired; the status keeps the last success. No network and no model: stages are replaced."""
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from oceanmind_environment import noaa_oisst as no
from oceanmind_environment import publish as pub
from oceanmind_environment import refresh_status as rs
from oceanmind_environment import schedule as sc

ROOT = Path(__file__).resolve().parents[1]


def generation(root: Path, latest: str, tag: str):
    """A minimal processed dataset ending on `latest`, with a marker file naming its generation."""
    (root / "cubes").mkdir(parents=True)
    (root / "model" / "dashboard").mkdir(parents=True)
    days = pd.date_range(pd.Timestamp(latest) - pd.Timedelta(days=9), latest)
    for name, part in (("train", days[:5]), ("val", days[5:7]), ("test", days[7:])):
        np.save(root / "cubes" / f"{name}_dates.npy", part.values)
    (root / "model" / "dashboard" / "heatwave.json").write_text(json.dumps({"latest_date": latest}))
    (root / "model" / "dashboard" / "snapshot.json").write_text(json.dumps({"latest": {"observed_date": latest, "target_dates": sc.forecast_window(latest)}}))
    np.savez(root / "region_series.npz", dates=np.array(days.values, dtype="datetime64[D]"))
    (root / "generation.txt").write_text(tag)
    return root


def tag(root: Path) -> str:
    return (root / "generation.txt").read_text()


# ------------------------------------------------------------------------------------------------ the directory swap
def test_the_swap_replaces_the_whole_generation_and_keeps_the_previous_one_until_finalised(tmp_path):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    new = generation(pub.staging_dir(live), "2026-10-27", "new")
    prev = pub.swap(live, new)
    assert tag(live) == "new" and tag(prev) == "old" and not new.exists()
    assert rs.check_consistency(live)["latest"] == "2026-10-27"
    pub.finalize(prev)
    assert not prev.exists()


def test_a_swap_that_cannot_complete_leaves_the_live_dataset_in_place(tmp_path, monkeypatch):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    new = generation(pub.staging_dir(live), "2026-10-27", "new")
    real = Path.rename

    def locked(self, target):                                   # a directory whose files are open cannot be renamed on Windows
        if self == live:
            raise PermissionError("in use")
        return real(self, target)
    with monkeypatch.context() as mp:
        mp.setattr(Path, "rename", locked)
        with pytest.raises(pub.PublishError, match="in use"):
            pub.swap(live, new, attempts=2, wait_s=0)
    assert tag(live) == "old" and new.exists()


def test_a_failure_after_the_first_rename_puts_the_previous_generation_back(tmp_path, monkeypatch):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    new = generation(pub.staging_dir(live), "2026-10-27", "new")
    real = Path.rename

    def fail_second(self, target):
        if self == new:
            raise OSError("disk error")
        return real(self, target)
    with monkeypatch.context() as mp:
        mp.setattr(Path, "rename", fail_second)
        with pytest.raises(pub.PublishError):
            pub.swap(live, new, attempts=1, wait_s=0)
    assert tag(live) == "old"


def test_an_interrupted_swap_is_repaired_on_the_next_start(tmp_path):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    live.rename(pub.previous_dir(live))                          # the process died between the two renames
    assert not live.exists()
    assert "restored" in pub.recover(live) and tag(live) == "old"
    assert pub.recover(live) is None


def test_rollback_after_a_bad_publication_restores_the_previous_generation(tmp_path):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    prev = pub.swap(live, generation(pub.staging_dir(live), "2026-10-27", "new"))
    assert prev.exists() and pub.rollback(live) is True and tag(live) == "old" and not prev.exists()


def test_side_files_of_the_live_dataset_survive_a_rebuild(tmp_path):
    live = generation(tmp_path / "processed", "2026-10-26", "old")
    (live / "figures").mkdir()
    (live / "figures" / "a.png").write_text("x")
    new = generation(pub.staging_dir(live), "2026-10-27", "new")
    assert "figures" in pub.carry_over(live, new) and (new / "figures" / "a.png").exists() and (new / "generation.txt").read_text() == "new"


# ------------------------------------------------------------------------------------------------ the staged build
def load_refresh():
    spec = importlib.util.spec_from_file_location("refresh_pacific", ROOT / "scripts" / "refresh_pacific.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Staged:
    """Replaces the preprocessing and model commands by functions that write a generation into the staging directory named in the temporary config."""

    def __init__(self, tmp_path, monkeypatch, latest="2026-10-27", fail_at=None, forecast_from=None, hw_latest=None):
        self.m = load_refresh()
        self.root = tmp_path
        self.out = generation(tmp_path / "processed_pacific", "2026-10-26", "old")
        self.calls, self.fail_at, self.latest, self.forecast_from, self.hw_latest = [], fail_at, latest, forecast_from, hw_latest
        monkeypatch.setattr(self.m, "ROOT", tmp_path)
        monkeypatch.setattr(self.m, "run", self.run)
        monkeypatch.setattr(self.m.time, "sleep", lambda s: None)
        monkeypatch.setattr(pub.time, "sleep", lambda s: None)

    def run(self, args, cwd=None):
        sub = args[2] if len(args) > 2 else ""
        self.calls.append(sub)
        if self.fail_at and sub == self.fail_at:
            raise RuntimeError(f"{sub} failed")
        stage = self.root / (self.out.name + ".staging")
        if sub == "build":
            generation(stage, self.latest, "new")
            for f in ("heatwave.json", "snapshot.json"):                       # the build alone leaves no forecast: evaluate/export write it
                (stage / "model" / "dashboard" / f).unlink()
        elif sub == "export-dashboard":
            (stage / "model" / "dashboard" / "heatwave.json").write_text(json.dumps({"latest_date": self.hw_latest or self.latest}))
            issued = self.forecast_from or self.latest
            (stage / "model" / "dashboard" / "snapshot.json").write_text(json.dumps({"latest": {"observed_date": issued, "target_dates": sc.forecast_window(issued)}}))

    def go(self):
        self.m.staged_build("config.pacific.yaml", self.out, None)


def test_a_successful_refresh_publishes_the_dataset_the_forecast_and_the_heatwaves_together(tmp_path, monkeypatch):
    s = Staged(tmp_path, monkeypatch)
    s.go()
    c = rs.check_consistency(s.out)
    assert tag(s.out) == "new" and c["consistent"] is True and c["latest"] == "2026-10-27"
    assert c["forecast_dates"] == ["2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03"]      # each valid date, from the day after the observation
    assert not pub.staging_dir(s.out).exists() and not pub.previous_dir(s.out).exists() and not (tmp_path / "config.pacific.staging.yaml").exists()
    assert s.calls == ["build", "evaluate", "export-dashboard", "build-sst-history"]


@pytest.mark.parametrize("stage", ["build", "evaluate", "export-dashboard"])
def test_a_failure_in_any_stage_leaves_the_published_dataset_untouched(tmp_path, monkeypatch, stage):
    s = Staged(tmp_path, monkeypatch, fail_at=stage)
    with pytest.raises(RuntimeError, match=stage):
        s.go()
    assert tag(s.out) == "old" and rs.check_consistency(s.out)["latest"] == "2026-10-26"
    assert not pub.staging_dir(s.out).exists() and not (tmp_path / "config.pacific.staging.yaml").exists()
    assert "build-sst-history" not in s.calls


def test_a_forecast_for_the_wrong_day_is_never_published(tmp_path, monkeypatch):
    s = Staged(tmp_path, monkeypatch, forecast_from="2026-10-26")               # the forecast generation failed to advance
    with pytest.raises(RuntimeError, match="inconsistent"):
        s.go()
    assert tag(s.out) == "old"


def test_stale_heatwave_results_are_never_published_with_a_newer_dataset(tmp_path, monkeypatch):
    s = Staged(tmp_path, monkeypatch, hw_latest="2026-10-26")
    with pytest.raises(RuntimeError, match="inconsistent"):
        s.go()
    assert tag(s.out) == "old"


def test_a_leftover_staging_directory_from_a_crashed_run_is_discarded(tmp_path, monkeypatch):
    s = Staged(tmp_path, monkeypatch)
    generation(pub.staging_dir(s.out), "2026-10-01", "crashed")
    s.go()
    assert tag(s.out) == "new"


def test_running_the_staged_build_twice_gives_the_same_published_dataset(tmp_path, monkeypatch):
    s = Staged(tmp_path, monkeypatch)
    s.go()
    first = rs.check_consistency(s.out)
    s.go()
    assert rs.check_consistency(s.out) == first and tag(s.out) == "new"


# ------------------------------------------------------------------------------------------------ status and the stored record
def test_the_last_success_survives_a_failed_attempt(tmp_path):
    a = rs.write_status(tmp_path, outcome="updated", latest_observation="2026-10-27", consistent=True)
    b = rs.write_status(tmp_path, outcome="source_unavailable", latest_observation="2026-10-27")
    c = rs.write_status(tmp_path, outcome="unchanged", latest_observation="2026-10-27", consistent=True)
    assert b["last_success_at"] == a["last_success_at"] and b["last_update_at"] == a["last_update_at"]
    assert c["last_success_at"] >= a["last_success_at"] and c["last_update_at"] == a["last_update_at"]           # nothing changed: success, but not an update
    assert rs.write_status(tmp_path, outcome="failed")["last_success_at"] == c["last_success_at"]


def test_an_inconsistent_attempt_is_not_a_success(tmp_path):
    assert rs.write_status(tmp_path, outcome="updated", consistent=False)["last_success_at"] is None


def test_the_stored_record_swap_never_leaves_no_record_and_recovers_from_a_crash(tmp_path):
    from test_noaa_oisst import make_store
    import xarray as xr
    store = make_store(tmp_path / "sst.zarr", days=6)
    new = make_store(tmp_path / "new.zarr", days=7)
    no.swap_store(new, store)
    with xr.open_zarr(store) as z:
        assert z.sizes["time"] == 7
    assert not store.with_name("sst.zarr.old").exists()
    store.rename(store.with_name("sst.zarr.old"))                              # crash between the renames
    assert no.recover_store(store) is True and store.exists()


def test_a_written_record_that_cannot_be_read_back_does_not_replace_the_store(tmp_path, monkeypatch):
    from test_noaa_oisst import make_store
    import xarray as xr
    store = make_store(tmp_path / "sst.zarr", days=6)
    with xr.open_zarr(make_store(tmp_path / "longer.zarr", days=8)) as z:
        longer = z.sst.load()
    real = xr.open_zarr

    def broken(path, *a, **k):
        if str(path).endswith(".tmp"):
            raise OSError("truncated")
        return real(path, *a, **k)
    with monkeypatch.context() as mp:
        mp.setattr(no.xr, "open_zarr", broken)
        with pytest.raises(no.SourceError, match="read back"):
            no._publish(longer, store, {"provider": "x"})
    with xr.open_zarr(store) as z:
        assert z.sizes["time"] == 6
    assert not store.with_name("sst.zarr.tmp").exists()


# ------------------------------------------------------------------------------------------------ the NCEI daily files: outages, retries, partial downloads
class Resp:
    def __init__(self, code, content=b""):
        self.status_code, self.content, self.text = code, content, ""


def _ncei_call(tmp_path, monkeypatch, responses):
    calls = []
    seq = iter(responses)

    def fake_get(url, **kw):
        calls.append(url)
        r = next(seq)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(no.requests, "get", fake_get)
    monkeypatch.setattr(no.time, "sleep", lambda s: None)
    lat, lon = np.array([0.5, 1.5]), np.array([100.5, 101.5])
    return no._ncei_day(pd.Timestamp("2026-10-28"), lat, lon, tmp_path), calls


def test_a_day_that_is_not_published_is_not_retried_and_is_reported_missing(tmp_path, monkeypatch):
    got, calls = _ncei_call(tmp_path, monkeypatch, [Resp(404), Resp(404)])               # the final file and the preliminary file
    assert got is None and len(calls) == 2


def test_a_timeout_or_server_error_is_retried_before_the_day_is_given_up(tmp_path, monkeypatch):
    import requests
    got, calls = _ncei_call(tmp_path, monkeypatch, [requests.Timeout("t"), Resp(503), Resp(503)] + [Resp(404)])
    assert got is None and len(calls) == 4                                               # three tries for the final file, then the preliminary file is simply not there


def test_a_partial_download_is_rejected_and_not_kept(tmp_path, monkeypatch):
    got, calls = _ncei_call(tmp_path, monkeypatch, [Resp(200, b"not a netcdf file"), Resp(404)])
    assert got is None
    assert not list(tmp_path.glob("ncei_*")) and not list(tmp_path.glob("*.part"))


def test_the_tail_of_a_source_outage_does_not_invent_observations(tmp_path, monkeypatch):
    from test_noaa_oisst import make_store
    import requests
    import xarray as xr
    store = make_store(tmp_path / "sst.zarr", days=6)
    monkeypatch.setattr(no, "server_days", lambda product: (_ for _ in ()).throw(no.SourceError("timed out")))
    monkeypatch.setattr(no, "expected_latest", lambda now=None, lag_days=1: pd.Timestamp("2024-03-09"))
    monkeypatch.setattr(no.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    monkeypatch.setattr(no.time, "sleep", lambda s: None)
    cfg = {"config_path": str(tmp_path / "c.yaml"), "environment_provider": {"domain": {"lat_max": 65.0, "lon_max": 290.0}, "time": {"start": "2024-01-01"},
                                                                              "source": {"cache_dir": str(tmp_path / "cache"), "store": str(store)}}}
    out = no.sync(cfg)
    assert out["updated"] is False and out["latest"] == "2024-03-06"
    with xr.open_zarr(store) as z:
        assert z.sizes["time"] == 6                                                       # the record is exactly what it was
