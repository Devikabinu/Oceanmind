"""What the application shows while and after the refresh publishes: data state (current, delayed, refresh failed), the forecast files of one generation only, and caches that follow
the files they were read from."""
import json
import os

import numpy as np
import pytest

from app.services import environment_store as es
from app.services import forecast_explain as fe
from app.services import forecast_store
from app.services.environment import OutputsUnavailable
from app.tests import _pacific as P
from app.tests.test_pacific_product import h, pac  # noqa: F401  (fixtures)
from app.tests.test_report_evidence import fake_sensitivity


def status_file(tmp_path, monkeypatch, **fields):
    f = tmp_path / "refresh_status.json"
    f.write_text(json.dumps({"attempted_at": "2026-10-29T06:00:00+00:00", "outcome": "updated", "message": "m", "latest_observation": P.LATEST, "forecast_dates": None, **fields}))
    monkeypatch.setattr(es, "refresh_status_file", lambda: f)
    return f


def fresh(pac, now):  # noqa: F811
    return es.get_store("pacific").freshness(now=now)


def test_data_are_current_when_the_newest_expected_day_is_present(pac, tmp_path, monkeypatch):  # noqa: F811
    status_file(tmp_path, monkeypatch, last_success_at="2026-10-29T06:00:00+00:00")
    f = fresh(pac, "2020-01-21 14:00")
    assert f["status"] == "current" and f["behind_expected"] == 0 and f["refresh"]["last_success_at"] == "2026-10-29T06:00:00+00:00"


def test_data_one_day_behind_are_delayed_not_current(pac, tmp_path, monkeypatch):  # noqa: F811
    status_file(tmp_path, monkeypatch, outcome="unchanged")
    f = fresh(pac, "2020-01-22 14:00")
    assert f["status"] == "delayed" and f["behind_expected"] == 1 and "not today" in f["message"]


def test_a_failed_refresh_behind_the_expected_day_is_reported_as_refresh_failed(pac, tmp_path, monkeypatch):  # noqa: F811
    status_file(tmp_path, monkeypatch, outcome="source_unavailable", last_success_at="2026-10-28T06:00:00+00:00")
    f = fresh(pac, "2020-01-23 14:00")
    assert f["status"] == "refresh failed" and "did not complete" in f["message"] and f["refresh"]["last_success_at"] == "2026-10-28T06:00:00+00:00"
    status_file(tmp_path, monkeypatch, outcome="failed")
    assert fresh(pac, "2020-01-23 14:00")["status"] == "refresh failed"


def test_a_failed_attempt_does_not_make_current_data_look_stale(pac, tmp_path, monkeypatch):  # noqa: F811
    status_file(tmp_path, monkeypatch, outcome="source_unavailable")
    assert fresh(pac, "2020-01-21 14:00")["status"] == "current"


def test_without_a_status_file_the_state_comes_from_the_dates_alone(pac, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(es, "refresh_status_file", lambda: tmp_path / "absent.json")
    f = fresh(pac, "2020-01-26 14:00")
    assert f["refresh"] is None and f["status"] == "stale"


# ------------------------------------------------------------------------------------------------ one generation of forecast files
def _write(pac, generation_npz, generation_json):  # noqa: F811
    d = pac / "model" / "dashboard"
    with np.load(d / "snapshot.npz") as z:
        data = {k: z[k] for k in z.files}
    if generation_npz is not None:
        data["generation"] = np.asarray(generation_npz)
    np.savez_compressed(d / "snapshot.npz", **data)
    info = json.loads((d / "snapshot.json").read_text())
    if generation_json is not None:
        info["generation"] = generation_json
    (d / "snapshot.json").write_text(json.dumps(info))


def test_forecast_files_of_two_different_refreshes_are_never_served_together(pac):  # noqa: F811
    forecast_store._read.cache_clear()
    _write(pac, "aaa", "bbb")
    with pytest.raises(OutputsUnavailable, match="being updated"):
        forecast_store.load("pacific")
    _write(pac, "bbb", "bbb")
    snap, info, _, _ = forecast_store.load("pacific")
    assert info["generation"] == "bbb" and str(snap["generation"]) == "bbb"


def test_files_written_before_generations_existed_are_still_served(pac):  # noqa: F811
    forecast_store._read.cache_clear()
    assert forecast_store.load("pacific")[1]["latest"]["observed_date"] == P.LATEST


def test_the_forecast_cache_follows_every_file_it_was_read_from(pac):  # noqa: F811
    forecast_store._read.cache_clear()
    assert forecast_store.load("pacific")[1]["latest"]["observed_date"] == P.LATEST
    d = pac / "model" / "dashboard"
    info = json.loads((d / "snapshot.json").read_text())
    info["latest"]["observed_date"] = "2020-01-21"
    (d / "snapshot.json").write_text(json.dumps(info))                              # only snapshot.json changes, the .npz keeps its time stamp
    os.utime(d / "snapshot.json", (1_900_000_000, 1_900_000_000))
    assert forecast_store.load("pacific")[1]["latest"]["observed_date"] == "2020-01-21"


# ------------------------------------------------------------------------------------------------ explanation cache
def test_a_new_forecast_generation_invalidates_the_cached_explanation(pac):  # noqa: F811
    fe._cache.clear()
    forecast_store._read.cache_clear()
    calls = []

    def runner(dataset, lat, lon):
        calls.append(1)
        return fake_sensitivity(dataset, lat, lon)
    fe.explain("pacific", -10, 122, runner=runner)
    fe.explain("pacific", -10, 122, runner=runner)
    assert len(calls) == 1                                                              # the same inputs: served from the cache
    d = pac / "model" / "dashboard"
    os.utime(d / "snapshot.npz", (1_900_000_000, 1_900_000_000))                        # a refresh rewrote the forecast
    fe.explain("pacific", -10, 122, runner=runner)
    assert len(calls) == 2


def test_an_explanation_is_not_given_for_a_forecast_older_than_the_data(pac, monkeypatch):  # noqa: F811
    fe._cache.clear()
    forecast_store._read.cache_clear()
    d = pac / "model" / "dashboard"
    info = json.loads((d / "snapshot.json").read_text())
    info["latest"]["observed_date"] = "2020-01-18"
    (d / "snapshot.json").write_text(json.dumps(info))
    out = fe.explain("pacific", -10, 122, runner=fake_sensitivity)
    assert out["available"] is False and "not explained as if it were current" in out["message"]


# ---- the publication-time rule, the same on the backend side as in oceanmind_environment.schedule
@pytest.mark.parametrize("now, expected", [("2026-10-30 04:49", "2026-10-28"), ("2026-10-30 13:44", "2026-10-28"), ("2026-10-30 13:45", "2026-10-29"), ("2026-10-30 19:15+05:30", "2026-10-29"), ("2026-10-30 19:14+05:30", "2026-10-28")])
def test_the_backend_expects_the_day_noaa_has_published_by_now(now, expected):
    assert str(es.expected_latest_day(now).date()) == expected


def test_a_dataset_that_lacks_a_day_noaa_has_published_is_delayed_and_the_message_says_what_is_missing(pac, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(es, "refresh_status_file", lambda: tmp_path / "none.json")
    f = fresh(pac, "2020-01-22 04:00")                                                        # 2020-01-21 was posted on the 22nd at 13:31 UTC? not yet: only 2020-01-20 exists
    assert f["status"] == "current" and "newest NOAA should have published" in f["message"]
    f = fresh(pac, "2020-01-22 14:00")
    assert f["status"] == "delayed" and "NOAA should have published 2020-01-21 by now" in f["message"] and "not today" in f["message"]


def test_a_refresh_that_started_and_never_finished_is_reported_as_interrupted_not_as_running_forever(pac, tmp_path, monkeypatch):  # noqa: F811
    from datetime import datetime, timedelta, timezone
    f = status_file(tmp_path, monkeypatch, outcome="running", attempted_at=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds"))
    assert es.refresh_status()["outcome"] == "running"
    status_file(tmp_path, monkeypatch, outcome="running", attempted_at=(datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(timespec="seconds"))
    r = es.refresh_status()
    assert r["outcome"] == "interrupted" and "never finished" in r["message"]
    assert fresh(pac, "2020-01-23 14:00")["status"] == "refresh failed"                       # behind the expected day and the last attempt did not finish
    assert fresh(pac, "2020-01-21 14:00")["status"] == "current"
