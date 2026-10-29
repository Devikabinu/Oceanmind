"""Historical SST: retrieval for a location and for regions, aggregation, annual means, trend rules, missing data, validation and dataset selection."""
import numpy as np
import pandas as pd
import pytest

from app.services import environment_store as es
from app.services import forecast_store, risk_service
from app.services import heatwave_service as hws
from app.services import sst_history as sh
from app.tests import _forecast as F
from app.tests import _heatwaves as HW
from app.tests import _pacific as P
from app.tests._helpers import auth_headers


@pytest.fixture
def pac(tmp_path, monkeypatch):
    root = tmp_path / "pacific"
    P.build(root)
    HW.build(root)
    F.build(root)
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: root)
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    sh._cache.clear()
    for c in (es.clear_cache, risk_service._inputs_cache.clear, hws._read_dir.cache_clear, forecast_store._read.cache_clear):
        c()
    yield root
    sh._cache.clear()
    es.clear_cache()


@pytest.fixture
def h(client):
    return auth_headers(client)


def get(client, h, **params):
    return client.get("/api/environment/sst-history", params={"dataset": "pacific", **params}, headers=h)


def years(first, last, fn, gap_years=()):
    """Daily frame whose annual mean anomaly follows fn(year); years in gap_years have no data."""
    idx = pd.date_range(f"{first}-01-01", f"{last}-12-31")
    an = np.array([fn(d.year) for d in idx], dtype=float)
    for y in gap_years:
        an[idx.year == y] = np.nan
    return pd.DataFrame({"sst": 20 + an, "anom": an}, index=idx)


# ---- retrieval -------------------------------------------------------------------------------------------------------------------------
def test_region_series_matches_the_area_weighted_mean_of_the_cubes(client, h, pac):
    b = get(client, h, aggregation="daily").json()
    assert b["period"]["start"] == "2020-01-01" and b["period"]["end"] == P.LATEST and len(b["series"]) == 20
    s = es.get_store("pacific")
    values, status, t = s.native_layer("sst", P.LATEST)
    w = np.cos(np.deg2rad(s.lat))[:, None] * np.ones((1, len(s.lon)))
    ok = np.isfinite(values)
    expected = float((values[ok] * w[ok]).sum() / w[ok].sum())
    assert b["series"][-1]["date"] == P.LATEST and b["series"][-1]["sst"] == pytest.approx(expected, abs=0.01)
    assert b["scope"] == {"type": "region", "name": "Entire Pacific Ocean"} and b["location"] is None and b["kind"] == "generated"
    assert b["statistics"]["observations"] == 20 and b["statistics"]["missing_days"] == 0 and b["statistics"]["cells"] > 0


def test_regions_give_different_series_and_a_region_without_cells_is_refused(client, h, pac):
    whole = get(client, h, aggregation="daily").json()["series"][-1]["sst"]
    west = get(client, h, region="western_pacific", aggregation="daily").json()
    east = get(client, h, region="eastern_pacific", aggregation="daily").json()
    assert west["region"]["id"] == "western_pacific" and west["series"][-1]["sst"] != east["series"][-1]["sst"] != whole
    assert get(client, h, region="atlantis").status_code == 404


def test_location_series_reads_one_cell_and_longitudes_in_either_convention_agree(client, h, pac):
    a = get(client, h, lat=-10.0, lon=-170.0, aggregation="daily").json()
    b = get(client, h, lat=-10.0, lon=190.0, aggregation="daily").json()
    assert a["scope"]["type"] == "location" and a["location"]["latitude"] == -10.0 and a["statistics"]["cells"] == 1
    assert a["series"] == b["series"] and a["location"]["cell"]["lon"] == b["location"]["cell"]["lon"]
    point = es.point_response("pacific", -10.0, -170.0, P.LATEST)
    assert a["series"][-1]["sst"] == pytest.approx(point["sst"], abs=0.01)
    assert a["series"][-1]["anomaly"] == pytest.approx(point["anomaly"], abs=0.01)


def test_a_clicked_location_changes_the_result(client, h, pac):
    a = get(client, h, lat=-10.0, lon=-170.0, aggregation="daily").json()["series"][-1]["sst"]
    b = get(client, h, lat=40.0, lon=-170.0, aggregation="daily").json()["series"][-1]["sst"]
    assert a != b


def test_invalid_and_unusable_coordinates_are_rejected_with_a_reason(client, h, pac):
    assert get(client, h, lat=95, lon=0).status_code == 422
    assert get(client, h, lat=0, lon=400).status_code == 422
    one = get(client, h, lat=0)
    assert one.status_code == 422 and "together" in one.json()["detail"]["message"]
    land = get(client, h, lat=30.0, lon=120.0)                                    # the test grid's land block
    assert land.status_code == 422 and "land" in land.json()["detail"]["message"]
    out = get(client, h, lat=-85, lon=0)
    assert out.status_code == 422 and "outside the dataset" in out.json()["detail"]["message"]


# ---- dates, aggregation, datasets ------------------------------------------------------------------------------------------------------
def test_date_ranges_are_clipped_to_the_record_and_validated(client, h, pac):
    b = get(client, h, aggregation="daily", start_date="2020-01-05", end_date="2020-01-08").json()
    assert [x["date"] for x in b["series"]] == ["2020-01-05", "2020-01-06", "2020-01-07", "2020-01-08"]
    c = get(client, h, aggregation="daily", start_date="2019-01-01", end_date="2020-01-03").json()
    assert c["period"]["start"] == "2020-01-01" and c["period"]["available_start"] == "2020-01-01" and len(c["series"]) == 3
    assert get(client, h, start_date="2020-01-09", end_date="2020-01-02").status_code == 422
    gone = get(client, h, start_date="2010-01-01", end_date="2010-12-31")
    assert gone.status_code == 404 and gone.json()["detail"]["code"] == "no_data_for_date"
    assert get(client, h, start_date="not-a-date").status_code == 422


def test_aggregation_levels(client, h, pac):
    m = get(client, h, aggregation="monthly").json()
    assert [x["date"] for x in m["series"]] == ["2020-01-01"] and m["series"][0]["observations"] == 20
    y = get(client, h, aggregation="annual").json()
    assert [x["date"] for x in y["series"]] == ["2020-01-01"]                      # the open final year is shown, flagged incomplete below
    assert y["annual_summary"][0]["complete"] is False and y["annual_summary"][0]["observations"] == 20 and y["annual_summary"][0]["expected_days"] == 20
    assert get(client, h, aggregation="hourly").status_code == 422


def test_a_short_record_gives_no_trend_and_says_why(client, h, pac):
    b = get(client, h).json()
    assert b["trend"]["direction"] == "insufficient_data" and b["trend"]["slope_per_year"] is None
    assert "Insufficient historical data for trend estimation" in b["trend"]["message"]
    assert b["change"] is None and b["percent_change"] is None and "not scientifically meaningful" in b["percent_change_note"]
    assert "SST trend over the available historical record (2020-2020)" in b["statement"]


def test_forecast_is_returned_separately_and_never_inside_the_observed_series(client, h, pac):
    b = get(client, h, aggregation="daily").json()
    f = b["forecast"]
    assert f["kind"] == "forecast" and "not an observation" in f["label"] and len(f["series"]) == 7
    assert min(x["date"] for x in f["series"]) > max(x["date"] for x in b["series"])
    assert {x["date"] for x in f["series"]}.isdisjoint({x["date"] for x in b["series"]})
    loc = get(client, h, lat=-10.0, lon=-170.0, aggregation="daily").json()
    assert loc["forecast"]["kind"] == "forecast" and len(loc["forecast"]["series"]) == 7


def test_dataset_selection(client, h, pac):
    assert get(client, h).json()["dataset"]["id"] == "pacific"
    r = client.get("/api/environment/sst-history", params={"dataset": "atlantic"}, headers=h)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "unknown_dataset"


def test_requires_sign_in(client, pac):
    assert client.get("/api/environment/sst-history", params={"dataset": "pacific"}).status_code in (401, 403)


# ---- annual aggregation and trend (pure functions, multi-year) ----------------------------------------------------------------------------
def test_annual_means_are_computed_from_the_daily_values_and_incomplete_years_are_marked():
    df = years(2010, 2020, lambda y: 0.1 * (y - 2010))
    df = df.loc["2010-01-01":"2020-06-30"]
    ann = sh.annual_summary(df, df.index[0], df.index[-1])
    assert [a["year"] for a in ann] == list(range(2010, 2021))
    assert ann[3]["mean_sst"] == pytest.approx(20.3) and ann[3]["mean_anomaly"] == pytest.approx(0.3) and ann[3]["observations"] == 365 and ann[3]["complete"] is True
    assert ann[-1]["observations"] == 182 and ann[-1]["complete"] is False                       # a half year never counts as a year


def test_missing_values_are_left_out_not_zeroed():
    df = years(2010, 2012, lambda y: 1.0)
    df.loc["2011-01-01":"2011-02-28", ["sst", "anom"]] = np.nan                                  # 59 days without data
    ann = {a["year"]: a for a in sh.annual_summary(df, df.index[0], df.index[-1])}
    assert ann[2011]["observations"] == 365 - 59 and ann[2011]["mean_anomaly"] == pytest.approx(1.0)   # zero-filling would give 0.84
    assert ann[2011]["coverage"] == pytest.approx(306 / 365, abs=0.001) and ann[2011]["complete"] is False       # 84% of the days: shown, but not used for the trend


def test_a_year_with_less_than_90_percent_of_its_days_is_not_complete():
    df = years(2010, 2010, lambda y: 1.0)
    df.iloc[:60] = np.nan
    assert sh.annual_summary(df, df.index[0], df.index[-1])[0]["complete"] is False


def test_trend_recovers_a_known_slope_and_marks_it_significant():
    df = years(2000, 2019, lambda y: 0.05 * (y - 2000) + (0.02 if y % 2 else -0.02))
    t = sh.trend(sh.annual_summary(df, df.index[0], df.index[-1]))
    assert t["slope_per_year"] == pytest.approx(0.05, abs=0.005) and t["direction"] == "warming" and t["significant"] is True and t["n_years"] == 20
    assert t["ci95"][0] < 0.05 < t["ci95"][1] and t["span_years"] == 19 and "not an attribution to climate change" in t["message"]
    fit = t["anomaly_at_reference_year"] + t["slope_per_year"] * (2019 - t["reference_year"])
    assert fit == pytest.approx(0.05 * 19, abs=0.05)


def test_cooling_and_no_trend():
    cooling = sh.trend(sh.annual_summary(*(lambda d: (d, d.index[0], d.index[-1]))(years(2000, 2015, lambda y: -0.03 * (y - 2000) + (0.01 if y % 2 else -0.01)))))
    assert cooling["direction"] == "cooling" and cooling["slope_per_year"] < 0
    rng = np.random.default_rng(3)
    noise = {y: rng.normal(0, 0.3) for y in range(2000, 2016)}
    flat = sh.trend(sh.annual_summary(*(lambda d: (d, d.index[0], d.index[-1]))(years(2000, 2015, lambda y: noise[y]))))
    assert flat["direction"] == "stable" and flat["significant"] is False


def test_trend_needs_enough_complete_years_and_ignores_gap_years():
    few = years(2000, 2005, lambda y: 0.1 * (y - 2000))
    assert sh.trend(sh.annual_summary(few, few.index[0], few.index[-1]))["direction"] == "insufficient_data"
    gappy = years(2000, 2012, lambda y: 0.1 * (y - 2000), gap_years=(2003, 2004, 2005, 2006, 2007))      # only 8 usable years remain: 13 - 5
    t = sh.trend(sh.annual_summary(gappy, gappy.index[0], gappy.index[-1]))
    assert t["n_years"] == 8 and 2005 not in t["years_used"] and t["direction"] == "warming"
    worse = years(2000, 2012, lambda y: 0.1 * (y - 2000), gap_years=(2003, 2004, 2005, 2006, 2007, 2008))
    assert sh.trend(sh.annual_summary(worse, worse.index[0], worse.index[-1]))["direction"] == "insufficient_data"


def test_monthly_means_need_enough_days():
    df = years(2010, 2010, lambda y: 1.0)
    df.loc["2010-03-01":"2010-03-25", ["sst", "anom"]] = np.nan                                    # March keeps 6 days only
    months = [x["date"] for x in sh._aggregate(df, "monthly")]
    assert "2010-03-01" not in months and "2010-02-01" in months and len(months) == 11


# ---- automatic refresh: freshness against the expected day, and the history cache following the dataset ---------------------------------------
def test_freshness_compares_the_newest_day_with_the_day_expected_after_the_one_day_lag(pac, monkeypatch, tmp_path):
    s = es.get_store("pacific")                                                      # newest observation: 2020-01-20
    assert s.freshness("2020-01-21 08:00")["status"] == "current" and s.freshness("2020-01-21")["expected_date"] == "2020-01-20"
    d = s.freshness("2020-01-23")
    assert d["status"] == "delayed" and d["behind_expected"] == 2 and "2020-01-22 was expected" in d["message"] and "not today" in d["message"]
    st = s.freshness("2020-03-01")
    assert st["status"] == "stale" and st["observation_date"] == P.LATEST and st["behind_expected"] > 2
    assert s.freshness("2020-01-19")["behind_expected"] == 0                          # never negative


def test_freshness_exposes_the_outcome_of_the_last_refresh_so_stale_data_are_explained(pac, monkeypatch, tmp_path):
    f = tmp_path / "refresh_status.json"
    f.write_text('{"attempted_at": "2026-10-28T03:00:00+00:00", "outcome": "source_unavailable", "message": "NOAA could not be reached; the previous valid dataset is kept.", '
                 '"latest_observation": "2020-01-20", "expected_latest": "2026-10-27", "forecast_dates": ["2020-01-21"], "consistent": true, "problems": []}')
    monkeypatch.setattr(es, "refresh_status_file", lambda: f)
    r = es.get_store("pacific").freshness("2026-10-28")["refresh"]
    assert r["outcome"] == "source_unavailable" and "previous valid dataset is kept" in r["message"] and r["latest_observation"] == "2020-01-20"
    f.unlink()
    assert es.get_store("pacific").freshness("2026-10-28")["refresh"] is None


def test_history_cache_is_rebuilt_when_the_dataset_is_rebuilt(client, h, pac):
    first = get(client, h, aggregation="daily").json()
    cache = pac / sh.CACHE_NAME
    assert cache.exists() and first["period"]["end"] == P.LATEST
    built = cache.stat().st_mtime
    # the dataset is rebuilt (meta.json is rewritten) without a new cache: the old one must not be served
    import os
    import time
    time.sleep(0.05)
    os.utime(pac / "meta.json", None)
    es.clear_cache()
    sh._cache.clear()
    get(client, h, aggregation="daily")
    assert cache.stat().st_mtime > built


def test_a_running_api_lets_go_of_the_dataset_while_the_cubes_are_rebuilt(pac, tmp_path, monkeypatch):
    from app.services import refresh_guard as rg
    marker = tmp_path / "dataset_rebuild.lock"
    monkeypatch.setattr(rg, "marker_file", lambda: marker)
    assert rg.rebuilding() is False and es.get_store("pacific") is es.get_store("pacific")
    marker.write_text("rebuilding")
    assert rg.rebuilding() is True
    with pytest.raises(es.DatasetUnavailable, match="being refreshed"):
        es.get_store("pacific")
    rg.release_all()
    assert es._store_cached.cache_info().currsize == 0                                # nothing stays cached, so no cube stays mapped
    import os
    os.utime(marker, (1, 1))                                                          # a marker left behind by a crashed build expires
    assert rg.rebuilding() is False
    assert es.get_store("pacific") is not None
