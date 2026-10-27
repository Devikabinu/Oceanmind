"""Historical marine-heatwave events, the heatwave layer for past dates, the anomaly analysis, the extra alert types and the freshness fields, on the small test Pacific."""
import numpy as np
import pytest

from app.services import environment_store as es
from app.services import heatwave_service as hws
from app.services import risk_service as risk
from app.tests import _heatwaves as HW
from app.tests import _pacific as P
from app.tests._helpers import auth_headers


@pytest.fixture
def pac(tmp_path, monkeypatch):
    root = tmp_path / "pacific"
    P.build(root)
    HW.build(root)
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: root)
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    for f in (es.clear_cache, risk._inputs_cache.clear, hws._read_dir.cache_clear, hws._read_history.cache_clear):
        f()
    risk._overlap_cache.update(key=None)
    yield root
    for f in (es.clear_cache, risk._inputs_cache.clear, hws._read_dir.cache_clear, hws._read_history.cache_clear):
        f()


@pytest.fixture
def h(client):
    return auth_headers(client)


def get(client, h, path, **params):
    return client.get(path, params={"dataset": "pacific", **params}, headers=h)


def test_history_lists_current_and_past_events_with_their_dates(client, h, pac):
    b = get(client, h, "/api/heatwaves/history").json()
    assert b["total"] == 4 and b["first_date"] == "2020-01-01" and b["last_date"] == "2020-01-20"
    by_status = {e["status"] for e in b["items"]}
    assert by_status == {"ACTIVE", "ENDED"}
    past = next(e for e in b["items"] if e["status"] == "ENDED")
    assert (past["start_date"], past["end_date"], past["duration_days"]) == ("2020-01-01", "2020-01-08", 8)
    assert [e["start_date"] for e in b["items"]] == sorted((e["start_date"] for e in b["items"]), reverse=True)        # most recent first
    assert b["provenance"]["is_observational"] is False and "evolution" not in b["items"][0]


@pytest.mark.parametrize("params, expected", [
    ({"status": "ENDED"}, 1), ({"status": "active"}, 3), ({"min_category": 3}, 1), ({"min_category": 2}, 2), ({"year": 2020}, 4), ({"year": 2019}, 0),
    ({"start": "2020-01-15"}, 3), ({"end": "2020-01-05"}, 1), ({"region": "polynesia"}, 1), ({"region": "east_asia"}, 0),
])
def test_history_filters(client, h, pac, params, expected):
    assert get(client, h, "/api/heatwaves/history", **params).json()["total"] == expected


def test_history_sorting_and_limit(client, h, pac):
    b = get(client, h, "/api/heatwaves/history", sort="duration", limit=2).json()
    assert [e["duration_days"] for e in b["items"]] == [14, 9] and b["total"] == 4
    assert get(client, h, "/api/heatwaves/history", sort="bogus").status_code == 422


def test_event_detail_has_evolution_and_a_footprint_for_any_day_of_the_event(client, h, pac):
    ev = next(e for e in get(client, h, "/api/heatwaves/history").json()["items"] if e["category"] == 3)
    d = get(client, h, f"/api/heatwaves/history/{ev['id']}").json()
    assert d["event"]["id"] == ev["id"] and len(d["evolution"]["dates"]) == 14 == len(d["evolution"]["area_km2"])
    fp = d["footprint"]
    assert fp["cells"] == 28 and fp["date"] == ev["peak_date"] and len(fp["anomaly_c"]) == 28
    assert min(fp["lon"]) < 180 < max(fp["lon"]) and any(x < 0 for x in fp["lon_180"])                   # one footprint on the continuous axis, across 180
    first = get(client, h, f"/api/heatwaves/history/{ev['id']}", date=ev["start_date"]).json()["footprint"]
    assert first["date"] == ev["start_date"] and first["cells"] == 28
    outside = get(client, h, f"/api/heatwaves/history/{ev['id']}", date="2020-01-02").json()["footprint"]
    assert outside["date"] == ev["peak_date"]                                                             # a day outside the event falls back to its peak
    assert d["current_event_ids"] and d["current_event_ids"][0].startswith("mhw-pacific-2020-01-20")      # links the past record to the current event
    assert d["biodiversity_evidence"] == "insufficient_coverage" and d["explanation"]


def test_past_event_is_not_linked_to_a_current_one_and_unknown_event_is_404(client, h, pac):
    past = next(e for e in get(client, h, "/api/heatwaves/history", status="ENDED").json()["items"])
    d = get(client, h, f"/api/heatwaves/history/{past['id']}").json()
    assert d["current_event_ids"] is None and d["event"]["status"] == "ENDED"
    assert get(client, h, "/api/heatwaves/history/mhw-pacific-h19990101-n00e000").status_code == 404


def test_events_in_progress_on_a_date(client, h, pac):
    on_past = get(client, h, "/api/heatwaves/on/2020-01-03").json()["items"]
    assert [e["status"] for e in on_past] == ["ENDED"] and on_past[0]["cells_on_date"] == 20
    on_last = get(client, h, "/api/heatwaves/on/2020-01-20").json()["items"]
    assert len(on_last) == 3 and all(e["status"] == "ACTIVE" for e in on_last)
    r = get(client, h, "/api/heatwaves/on/2019-12-01")
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_data_for_date"
    assert r.json()["detail"]["available_range"] == {"first": "2020-01-01", "last": "2020-01-20"}


def test_heatwave_map_for_a_past_date_shows_only_that_days_cells(client, h, pac):
    m = get(client, h, "/api/heatwaves/map", date="2020-01-03").json()
    vals = np.array([[np.nan if v is None else v for v in row] for row in m["values"]])
    assert m["date"] == "2020-01-03" and m["active_cells"] == 20 and np.isfinite(vals).sum() == 20          # only the past event: other cells are null, never 0
    assert set(vals[np.isfinite(vals)].tolist()) == {2.0}
    latest = get(client, h, "/api/heatwaves/map").json()
    assert latest["date"] == "2020-01-20" and latest["active_cells"] > 20
    assert get(client, h, "/api/heatwaves/map", date="2020-01-20").json()["active_cells"] == latest["active_cells"]
    assert get(client, h, "/api/heatwaves/map", date="2030-01-01").status_code == 404


def test_history_unavailable_is_reported_not_faked(client, h, pac):
    (pac / "model" / "dashboard" / "heatwave_history.json").unlink()
    hws._read_history.cache_clear()
    r = get(client, h, "/api/heatwaves/history")
    assert r.status_code == 503 and "have not been built" in r.json()["detail"]
    assert get(client, h, "/api/heatwaves").status_code == 200                                              # the current-event endpoints keep working


# ---- anomaly analysis ---------------------------------------------------------------------------------------------------
def test_anomaly_analysis_has_every_section_with_honest_statistics(client, h, pac):
    b = get(client, h, "/api/environment/anomaly-analysis").json()
    assert b["date"] == P.LATEST and b["region"]["id"] == "pacific" and b["threshold_c"] == 1.0
    s = b["summary"]
    assert s["valid_cells"] > 0 and 0 <= s["share_warm"] <= 1 and 0 <= s["share_cold"] <= 1
    assert b["timeline"]["dates"] and len(b["timeline"]["dates"]) == len(b["timeline"]["mean_anomaly_c"]) <= 20
    assert {r["id"] for r in b["regions"]} >= {"pacific", "polynesia"} and b["regions"] == sorted(b["regions"], key=lambda r: -r["mean_anomaly_c"])
    assert "not why" in b["method"] or "No specific cause" in " ".join(b["limits"]) or b["limits"]
    for c in b["strongest_warm"]:
        assert c["anomaly_c"] > 0 and c["region"]["name"]
        assert c["historical_percentile"] is None or 0 <= c["historical_percentile"] <= 100                  # short record: not ranked rather than guessed


def test_anomaly_analysis_thins_clusters_and_respects_region_and_date(client, h, pac):
    b = get(client, h, "/api/environment/anomaly-analysis", top=5).json()
    pts = [(c["lat"], c["lon"]) for c in b["strongest_warm"]]
    for i in range(len(pts)):
        for j in range(i):
            assert abs(pts[i][0] - pts[j][0]) > 6 or abs(pts[i][1] - pts[j][1]) > 6                          # one cell per area
    east = get(client, h, "/api/environment/anomaly-analysis", region="eastern_pacific").json()
    assert east["region"]["id"] == "eastern_pacific" and east["summary"]["valid_cells"] < b["summary"]["valid_cells"]
    earlier = get(client, h, "/api/environment/anomaly-analysis", date="2020-01-10").json()
    assert earlier["date"] == "2020-01-10" and len(earlier["timeline"]["dates"]) == 10
    assert get(client, h, "/api/environment/anomaly-analysis", date="2031-01-01").status_code == 404
    assert get(client, h, "/api/environment/anomaly-analysis", region="atlantis").status_code == 404


def test_persistence_counts_consecutive_days_beyond_the_threshold():
    from app.services.anomaly_analysis import streak_lengths
    block = np.full((10, 1, 5), 0.2, dtype="float32")
    block[:, 0, 0] = 1.5                      # warm every day: 10 days
    block[6:, 0, 1] = 1.2                     # warm for the last 4 days only
    block[:, 0, 2] = -1.3                     # cold every day
    block[:, 0, 3] = 1.4
    block[5, 0, 3] = 0.3                      # a single dip interrupts the run: 4 days
    block[:, 0, 4] = np.nan                   # no data: never a streak, never zero-filled into one
    block[-1, 0, 2] = -1.1
    assert streak_lengths(block, 1.0)[0].tolist() == [10, 4, 10, 4, 0]
    flipped = block.copy()
    flipped[:3, 0, 0] = -1.5                  # the sign changed earlier: only the warm days count
    assert streak_lengths(flipped, 1.0)[0, 0] == 7


# ---- freshness, provenance --------------------------------------------------------------------------------------------
def test_dataset_description_carries_freshness_and_update_information(client, h, pac):
    d = next(x for x in client.get("/api/environment/datasets", headers=h).json()["datasets"] if x["id"] == "pacific")
    f = d["freshness"]
    assert f["observation_date"] == P.LATEST and f["status"] == "stale" and f["days_behind"] > 14                  # a 2020 record is never presented as current
    assert "not today" in f["message"]
    assert d["processed_at"].endswith("+00:00") and d["limitations"] and d["temporal_resolution"] == "daily"
    assert "provider_id" in d["provider"]


# ---- new alert types --------------------------------------------------------------------------------------------------
def test_dataset_alerts_include_extreme_anomaly_and_persistent_anomaly_alerts_with_exact_locations(client, h, pac, db_session):
    from app.services import dataset_alerts
    # push one cell far above normal on the latest day
    P.build(pac, hot=((20, 21), (20, 21), 4.5))
    es.clear_cache()
    out = dataset_alerts.generate(db_session, "pacific")
    assert out["SST_ANOMALY"] >= 1
    items = client.get("/api/alerts", params={"dataset": "pacific", "alert_type": "SST_ANOMALY", "page_size": 50}, headers=h).json()["items"]
    assert items
    ext = [a for a in items if a["details"]["kind"] == "extreme"]
    assert ext and ext[0]["severity"] == "CRITICAL" and ext[0]["details"]["location"]["lat"] == pytest.approx(P.LAT[20])
    assert ext[0]["details"]["driver"] == "SST anomaly" and "do not establish a cause" in " ".join(ext[0]["details"]["reasons"])
    assert ext[0]["details"]["date"] == P.LATEST and ext[0]["details"]["region_id"]
    again = dataset_alerts.generate(db_session, "pacific")                                                         # idempotent: nothing is created twice
    assert again["SST_ANOMALY"] == 0


def test_species_of_a_historical_event_are_the_records_in_its_cells_not_in_its_bounding_box(client, h, pac, db_session):
    import datetime as dt
    from app.tests._helpers import make_biodiversity_observation, make_dataset
    ds = make_dataset(db_session)
    now = dt.datetime.now(dt.timezone.utc)
    make_biodiversity_observation(db_session, ds, ts=now, lat=10, lon=-178)           # inside the antimeridian event (182E)
    make_biodiversity_observation(db_session, ds, ts=now, lat=18, lon=174)            # the footprint corner cell (18N, 174E)
    make_biodiversity_observation(db_session, ds, ts=now, lat=30, lon=190)            # far outside
    db_session.commit()
    ev = next(e for e in get(client, h, "/api/heatwaves/history").json()["items"] if e["category"] == 3)
    d = get(client, h, f"/api/heatwaves/history/{ev['id']}").json()
    assert d["biodiversity_evidence"] == "observed" and sum(s["n_records"] for s in d["species_in_area"]) == 2
    assert "in the cells this event covered on" in d["species_note"]
