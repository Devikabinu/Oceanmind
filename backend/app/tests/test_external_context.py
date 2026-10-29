"""OBIS biodiversity and NOAA ERDDAP context: query geometry, tier selection, retries, caching and fallbacks, exposure to the heatwave and the predicted anomaly area, and how the report
uses them. No test reaches the network: every HTTP call is replaced by canned data."""
import time
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
import requests

from app.services import biodiversity_view as bv
from app.services import obis_live as oc
from app.services import obis_service as osv
from app.services import ocean_context as ctx
from app.tests._helpers import make_dataset
from app.tests.test_pacific_product import h, pac, report  # noqa: F401  (fixtures)
from app.tests.test_risk_scoring import inputs

TODAY = date(2026, 10, 28)


# ------------------------------------------------------------------------------------------------ query geometry and client
def test_boxes_are_polygons_and_split_at_the_antimeridian():
    assert oc.geometry(0, -150, 2).startswith("POLYGON((-152 -2,-148 -2,-148 2,-152 2,-152 -2))")
    east = oc.geometry(10, 179, 10)
    assert east.startswith("MULTIPOLYGON") and "180" in east and "-180" in east and "-171" in east                # 189 wraps to -171
    west = oc.geometry(10, -179, 10)
    assert west.startswith("MULTIPOLYGON") and "((171 " in west and "-189" not in west and ",-169 " in west
    assert oc.geometry(95, 0, 5).count("90") >= 1 and "95" not in oc.geometry(95, 0, 5)                           # latitude is clamped


def test_the_client_retries_then_gives_up_and_never_invents_a_result(monkeypatch):
    calls = []

    def flaky(url, params=None, timeout=None, headers=None):
        calls.append(1)
        if len(calls) < 3:
            raise requests.Timeout()

        class R:
            status_code, text = 200, ""
            def json(self): return {"total": 7}
        return R()
    monkeypatch.setattr(oc.requests, "get", flaky)
    monkeypatch.setattr(oc.time, "sleep", lambda s: None)
    assert oc.total(0, 0, 1) == 7 and len(calls) == 3
    monkeypatch.setattr(oc.requests, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError()))
    with pytest.raises(oc.ObisError, match="unavailable"):
        oc.total(0, 0, 1)


def test_the_client_enforces_a_minimum_interval_between_requests(monkeypatch):
    stamps = []

    class R:
        status_code = 200
        def json(self): return {"total": 1}
    monkeypatch.setattr(oc.requests, "get", lambda *a, **k: stamps.append(time.monotonic()) or R())
    oc._last[0] = 0.0
    for _ in range(3):
        oc.total(0, 0, 1)
    assert min(b - a for a, b in zip(stamps, stamps[1:])) >= oc.MIN_INTERVAL_S * 0.9


# ------------------------------------------------------------------------------------------------ tier selection
def fake_obis(monkeypatch, recent_by_half, all_by_half=None, species=None, records=None):
    monkeypatch.setattr(oc, "total", lambda lat, lon, half, start=None: (recent_by_half if start else (all_by_half or recent_by_half)).get(half, 0))
    monkeypatch.setattr(oc, "checklist", lambda lat, lon, half, start=None, redlist=False, size=1000: [r for r in (species or []) if not redlist or r.get("category")])
    monkeypatch.setattr(oc, "occurrences", lambda lat, lon, half, start=None, redlist=False, limit=3000: [r for r in (records or []) if not redlist or r.get("category")])


SPECIES = [{"scientificName": "Sphyrna lewini", "taxonRank": "Species", "taxonID": 1, "class": "Elasmobranchii", "category": "CR", "records": 6},
           {"scientificName": "Chaetodon trichrous", "taxonRank": "Species", "taxonID": 2, "class": "Teleostei", "records": 5},
           {"scientificName": "Sebastes", "taxonRank": "Genus", "taxonID": 3, "class": "Teleostei", "records": 9}]
RECORDS = [{"id": "a", "species": "Sphyrna lewini", "scientificName": "Sphyrna lewini", "decimalLatitude": 1.0, "decimalLongitude": -149.0, "eventDate": "2026-06-05T10:00:00+00:00", "datasetName": "d1", "category": "CR"},
           {"id": "b", "species": "Chaetodon trichrous", "scientificName": "Chaetodon trichrous", "decimalLatitude": -1.0, "decimalLongitude": -151.0, "eventDate": "2025-01-03T10:00:00+00:00", "datasetName": "d2"}]


def test_the_smallest_useful_box_is_used_and_its_scope_is_labelled(monkeypatch):
    fake_obis(monkeypatch, {0.5: 0, 2.0: 3, 5.0: 12, 10.0: 300, 20.0: 5000}, species=SPECIES, records=RECORDS)
    b = osv.build(0.0, -150.0, TODAY)
    assert b["available"] and b["half_width_deg"] == 10.0 and b["scope"] == "regional" and b["historical"] is False
    assert [t["records"] for t in b["trail"]] == [0, 3, 12, 300] and b["records_in_box"] == 300
    assert [s["scientific_name"] for s in b["species"]] == ["Sphyrna lewini", "Chaetodon trichrous"]               # threatened first, genus rows are not species
    assert b["species"][0]["category"] == "CR" and b["species"][0]["nearest_km"] > 0 and b["species"][0]["latest_record"] == "2026-06-05"
    fake_obis(monkeypatch, {0.5: 40}, species=SPECIES, records=RECORDS)
    assert osv.build(0.0, -150.0, TODAY)["scope"] == "local"


def test_older_records_are_used_only_when_no_box_has_recent_ones_and_are_labelled_historical(monkeypatch):
    fake_obis(monkeypatch, {}, all_by_half={5.0: 80}, species=SPECIES, records=RECORDS)
    b = osv.build(0.0, -150.0, TODAY)
    assert b["available"] and b["historical"] is True and b["window_start"] is None and b["scope"] == "nearby"
    fake_obis(monkeypatch, {}, all_by_half={}, species=[], records=[])
    n = osv.build(0.0, -150.0, TODAY)
    assert n["available"] is False and "fewer than 25" in n["message"]


# ------------------------------------------------------------------------------------------------ cache, background fetch and fallbacks
@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(osv, "ENABLED", True)
    calls = {"n": 0}

    def fake_build(lat, lon, today=None):
        calls["n"] += 1
        return {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": "Ocean Biodiversity Information System (OBIS)", "api": "https://api.obis.org/v3", "query": {}, "trail": [],
                "schema": osv.SCHEMA, "available": True, "scope": "nearby", "half_width_deg": 2.0, "historical": False, "window_start": "2024-10-28", "records_in_box": 60, "records_all_time": 900,
                "sampled_records": 2, "taxa": 3, "species": [], "records": []}
    monkeypatch.setattr(osv, "build", fake_build)
    return calls


def test_a_miss_fetches_once_and_every_later_click_is_served_from_the_cache(live):
    first = osv.location_biodiversity(0.0, -150.0, wait_s=5)
    assert first["status"] == "live" and first["available"] and live["n"] == 1
    again = osv.location_biodiversity(0.2, -150.1, wait_s=5)                                                      # the same 0.5 degree cache cell
    assert again["status"] == "cached" and live["n"] == 1
    assert osv.location_biodiversity(10.0, 170.0, wait_s=5)["status"] == "live" and live["n"] == 2                # a different place is a different key


def test_a_slow_fetch_does_not_block_the_click_and_finishes_in_the_background(monkeypatch, live):
    def slow(lat, lon, today=None):
        time.sleep(0.6)
        return osv.build.__wrapped__(lat, lon) if hasattr(osv.build, "__wrapped__") else {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "schema": osv.SCHEMA, "available": True, "scope": "local",
                                                                                           "half_width_deg": 0.5, "historical": False, "window_start": "x", "records_in_box": 30, "records_all_time": 30, "sampled_records": 0, "taxa": 0,
                                                                                           "species": [], "records": [], "trail": [], "api": "u", "source": "s", "query": {}}
    monkeypatch.setattr(osv, "build", slow)
    t = time.monotonic()
    r = osv.location_biodiversity(5.0, 5.0, wait_s=0.05)
    assert time.monotonic() - t < 0.5 and r["status"] == "refreshing" and r["available"] is False
    time.sleep(1.0)
    assert osv.location_biodiversity(5.0, 5.0, wait_s=0.05)["status"] == "cached"


def test_when_obis_fails_the_stale_cache_is_used_else_nothing_and_it_is_not_hammered(monkeypatch, live):
    osv.location_biodiversity(0.0, -150.0, wait_s=5)
    f = osv._file(osv._key(0.0, -150.0))
    old = osv.json.loads(f.read_text())
    old["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds")
    f.write_text(osv.json.dumps(old))
    n = {"n": 0}

    def boom(lat, lon, today=None):
        n["n"] += 1
        raise oc.ObisError("down")
    monkeypatch.setattr(osv, "build", boom)
    r = osv.location_biodiversity(0.0, -150.0, wait_s=5)
    assert r["status"] == "stale_cache" and r["available"] is True
    osv.location_biodiversity(0.0, -150.0, wait_s=5)
    assert n["n"] == 1                                                                                            # a failed place is not retried for a few minutes
    none = osv.location_biodiversity(40.0, 40.0, wait_s=5)
    assert none["status"] == "unavailable" and none["available"] is False


def test_switched_off_means_no_network_and_no_block(monkeypatch):
    monkeypatch.setattr(osv, "ENABLED", False)
    assert osv.location_biodiversity(0.0, 0.0) is None
    monkeypatch.setattr(ctx, "ENABLED", False)
    assert ctx.location_context(0.0, 0.0) is None


# ------------------------------------------------------------------------------------------------ exposure
def test_exposure_counts_species_and_records_in_the_heatwave_and_the_predicted_anomaly_area():
    inp = inputs(anom=1.5, forecast=0.2)
    inp.forecast_anomaly[:, 2:, 2:] = 1.5                                      # the predicted anomaly area: the south-east corner
    hw = np.zeros((4, 4), dtype=bool)
    hw[:2, :2] = True                                                          # the heatwave footprint: the north-west corner
    recs = [[0, 0, "A", "2026-01-01", "CR"], [1, 1, "A", "2026-01-02", "CR"], [0, 1, "B", "2026-01-02", None], [3, 3, "C", "2026-01-03", "EN"], [2, 2, "B", "2026-01-03", None], [1, 3, "D", "2026-01-03", "VU"]]
    o = bv.overlaps(recs, inp, hw, np.nanmean(inp.forecast_anomaly, axis=0))
    assert o["records_in_domain"] == 6
    assert o["heatwave"] == {"available": True, "records": 3, "species": 2, "threatened_species": 1, "share_pct": 50.0, "cells": 3, "cells_share_pct": 50.0, "species_share_pct": 50.0}
    assert o["cells_in_domain"] == 6 and o["species_in_domain"] == 4 and o["densest_cell_share_pct"] == pytest.approx(16.7, abs=0.1)
    assert o["forecast"]["records"] == 2 and o["forecast"]["species"] == 2 and o["forecast"]["threatened_species"] == 1 and o["forecast"]["share_pct"] == pytest.approx(33.3, abs=0.1)
    assert o["per_species"]["A"] == {"in_domain": 2, "in_heatwave": 2, "forecast_exposed": 0}
    none = bv.overlaps(recs, inp, None, None)
    assert none["heatwave"]["available"] is False and none["forecast"]["available"] is False                      # no footprint is not "0 exposed"


def test_the_view_distinguishes_scope_recency_and_threatened_species_and_never_claims_harm(db_session):
    bio = {"available": True, "status": "cached", "scope": "regional", "half_width_deg": 10.0, "historical": False, "window_start": "2024-10-28", "records_in_box": 300, "records_all_time": 5000,
           "sampled_records": 2, "taxa": 3, "trail": [{"half_width_deg": 0.5, "records": 0}], "fetched_at": "2026-10-27T10:00:00+00:00", "api": "https://api.obis.org/v3",
           "species": [{"scientific_name": "Sphyrna lewini", "aphia_id": 1, "group": "Elasmobranchii", "category": "CR", "records": 6, "sampled_records": 3, "nearest_km": 120, "latest_record": "2026-06-05", "datasets": ["d1"]},
                       {"scientific_name": "Old fish", "aphia_id": 2, "group": "Teleostei", "category": None, "records": 2, "sampled_records": 2, "nearest_km": 900, "latest_record": "2019-01-01", "datasets": []}],
           "records": [[1.0, 1.0, "Sphyrna lewini", "2026-06-05", "CR"], [0.0, 0.0, "Old fish", "2019-01-01", None]]}
    inp = inputs(anom=1.5, forecast=1.4)
    hw = np.zeros((4, 4), dtype=bool)
    hw[:2, :2] = True
    v = bv.view(db_session, bio, 0.0, inp, hw, today=TODAY)
    assert v["scope_label"] == "Regional occurrence" and v["counts"]["distinct_species"] == 2 and v["counts"]["threatened_species"] == 1 and v["counts"]["observations_all_time"] == 5000
    by = {i["scientific_name"]: i for i in v["items"]}
    assert by["Sphyrna lewini"]["recency"] == "Recent observation" and by["Old fish"]["recency"] == "Historical observation" and by["Old fish"]["conservation_status"] == "Not assessed"
    assert by["Sphyrna lewini"]["records_in_heatwave"] == 1 and v["threatened"][0]["scientific_name"] == "Sphyrna lewini"
    assert "potential exposure" in v["exposure_text"] and "not evidence of biological damage" in v["exposure_text"]
    assert v["provenance"]["source"].startswith("Ocean Biodiversity") and v["provenance"]["retrieved"] == "2026-10-27"
    unavailable = bv.view(db_session, {"available": False, "status": "refreshing", "message": "Fetching"}, 0.0)
    assert unavailable["available"] is False and bv.view(db_session, None, 0.0) is None


# ------------------------------------------------------------------------------------------------ ocean context
def _rows(values):
    return [{"time": t, "chlor_a": str(v)} for t, v in values]


def test_chlorophyll_is_context_with_its_dates_and_an_honest_comparison(monkeypatch):
    days = [(f"2026-10-{d:02d}T12:00:00Z", 0.30) for d in range(1, 17) for _ in range(4)]
    monthly = [(f"{y}-10-01T12:00:00Z", 0.10) for y in range(2012, 2026) for _ in range(4)] + [("2026-09-01T12:00:00Z", 0.2)] * 4

    def csv(url):
        if "time%5B(last)%5D" in url:
            return [{"time": "2026-10-17T12:00:00Z" if "daily" in url else "2026-09-01T12:00:00Z"}]
        return _rows(days) if "daily" in url else _rows(monthly)
    monkeypatch.setattr(ctx, "_csv", csv)
    c = ctx.chlorophyll(0.0, -150.0)
    assert c["available"] and c["latest"]["date"] == "2026-10-16" and c["dataset_end"] == "2026-10-17" and c["spatial_resolution"].startswith("0.0375")
    assert c["history"]["percentile"] == 100.0 and "elevated relative to the same month" in c["text"] and "ecological context" in c["text"] and "not a measurement of ecosystem productivity" in c["text"]


def test_no_cloud_free_pixels_gives_a_scoped_message_not_a_value(monkeypatch):
    monkeypatch.setattr(ctx, "_csv", lambda url: [{"time": "2026-10-17T12:00:00Z"}] if "time%5B(last)%5D" in url else _rows([("2026-10-16T12:00:00Z", "NaN")] * 8))
    c = ctx.chlorophyll(0.0, -150.0)
    assert c["available"] is False and "No cloud-free chlorophyll-a pixels" in c["message"]


def test_currents_give_speed_direction_and_change_without_naming_a_cause(monkeypatch):
    def csv(url):
        if "time%5B(last)%5D" in url:
            return [{"time": "2026-10-26T00:00:00Z"}]
        return [{"time": f"2026-10-{d}T00:00:00Z", "u_current": str(u), "v_current": str(v)} for d, u, v in ((20, 0.3, 0.0), (21, 0.3, 0.0), (22, 0.4, 0.0), (26, 0.9, 0.0))]
    monkeypatch.setattr(ctx, "_csv", csv)
    k = ctx.currents(20.0, -150.0)
    assert k["latest"]["speed"] == pytest.approx(0.9) and k["latest"]["direction_deg"] == 90 and "toward the east" in k["text"] and k["speed_change"] > 0.5
    assert "not an explanation of it" in k["text"] and "not an input of the forecast model" in k["text"] and "wind-driven" in k["caveat"]
    assert "unreliable within about 3° of the equator" in ctx.currents(1.0, -150.0)["caveat"]


def test_context_is_cached_and_a_failure_leaves_the_report_alone(monkeypatch):
    monkeypatch.setattr(ctx, "ENABLED", True)
    n = {"n": 0}

    def build(lat, lon):
        n["n"] += 1
        return {"schema": ctx.SCHEMA, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chlorophyll": {"available": True}, "currents": None, "errors": []}
    monkeypatch.setattr(ctx, "build", build)
    assert ctx.location_context(0.0, 0.0, wait_s=5)["status"] == "live"
    assert ctx.location_context(0.0, 0.0, wait_s=5)["status"] == "cached" and n["n"] == 1
    monkeypatch.setattr(ctx, "build", lambda lat, lon: (_ for _ in ()).throw(RuntimeError("down")))
    assert ctx.location_context(30.0, 30.0, wait_s=5) is None


# ------------------------------------------------------------------------------------------------ the report
def _bio_near(lat, lon):
    return {"available": True, "status": "cached", "scope": "nearby", "half_width_deg": 2.0, "historical": False, "window_start": "2024-10-28", "records_in_box": 80, "records_all_time": 4000,
            "sampled_records": 3, "taxa": 4, "trail": [{"half_width_deg": 0.5, "records": 0}, {"half_width_deg": 2.0, "records": 80}], "fetched_at": "2026-10-27T10:00:00+00:00", "api": "https://api.obis.org/v3",
            "species": [{"scientific_name": "Sphyrna lewini", "aphia_id": 9, "group": "Elasmobranchii", "category": "CR", "records": 6, "sampled_records": 2, "nearest_km": 40, "latest_record": "2026-06-05", "datasets": ["iNaturalist"]},
                        {"scientific_name": "Chaetodon trichrous", "aphia_id": 8, "group": "Teleostei", "category": None, "records": 74, "sampled_records": 1, "nearest_km": 90, "latest_record": "2026-08-01", "datasets": []}],
            "records": [[lat, lon, "Sphyrna lewini", "2026-06-05", "CR"], [lat, lon, "Sphyrna lewini", "2026-06-06", "CR"], [30.0, 150.0, "Chaetodon trichrous", "2026-08-01", None]]}


def test_the_report_carries_obis_exposure_context_sources_and_implications(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import location_report as lr
    monkeypatch.setattr(lr.obis_service, "location_biodiversity", lambda lat, lon, wait_s=4.0: _bio_near(-10.0, 122.0))
    monkeypatch.setattr(lr.ocean_context, "location_context", lambda lat, lon, wait_s=4.0: {"status": "cached", "errors": [], "currents": {
        "available": True, "text": "The geostrophic surface current is 0.40 m/s toward the east.", "source": "NOAA CoastWatch (NESDIS/STAR)", "dataset": "noaacwBLENDEDNRTcurrentsDaily", "latest": {"date": "2026-10-26"},
        "spatial_resolution": "0.25°", "temporal_resolution": "daily", "retrieved": "2026-10-28"}, "chlorophyll": {"available": True, "text": "Latest valid chlorophyll-a is 0.040 mg m⁻³.", "source": "NOAA CoastWatch / STAR",
        "dataset": "noaa_snpp_chla_daily", "latest": {"date": "2026-10-16"}, "spatial_resolution": "0.0375°", "temporal_resolution": "daily", "retrieved": "2026-10-28"}})
    r = report(client, h, -10, 122).json()
    o = r["obis"]
    assert o["available"] and o["scope_label"] == "Nearby observation" and o["counts"]["distinct_species"] == 2 and o["exposure"]["heatwave"]["records"] == 2 and o["exposure"]["heatwave"]["species"] == 1
    assert o["exposure"]["heatwave"]["threatened_species"] == 1 and "potential exposure" in o["exposure_text"]
    topics = {s["topic"]: s for s in r["sources"]}
    assert {"Sea surface temperature and anomaly", "7-day forecast", "Biodiversity", "Chlorophyll-a (ecological context)", "Surface currents (physical context)"} <= set(topics)
    assert topics["Biodiversity"]["source"].startswith("Ocean Biodiversity") and topics["Sea surface temperature and anomaly"]["source"] == "NOAA OISST v2.1" and topics["Sea surface temperature and anomaly"]["observation_date"] == r["date"]
    text = " ".join(i["text"] for i in r["implications"]["items"])
    assert "threatened" in text and "chlorophyll-a" in text.lower() and "surface current" in text.lower()
    assert r["risk"]["drivers"][0]["factor"] == "anomaly"                                                         # the score is computed from the project's own data, unchanged by the live summary


def test_the_report_survives_external_failures_and_falls_back_to_stored_records(client, h, pac, db_session, monkeypatch):  # noqa: F811
    from app.services import location_report as lr
    monkeypatch.setattr(lr.obis_service, "location_biodiversity", lambda *a, **k: {"available": False, "status": "unavailable", "message": "OBIS could not be reached; stored records are shown."})
    monkeypatch.setattr(lr.ocean_context, "location_context", lambda *a, **k: None)
    ds = make_dataset(db_session)
    from app.tests._helpers import make_biodiversity_observation
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
    o.scientific_name = "Stored fish"
    db_session.commit()
    r = report(client, h, -10, 122).json()
    assert r["obis"]["available"] is False and r["species"]["counted"]["observations"] == 1 and r["context"] is None
    assert any(s["topic"] == "Biodiversity" and s["source"].startswith("Stored OBIS") for s in r["sources"])


def test_spatial_variation_of_the_live_summary_is_not_faked(client, h, pac, monkeypatch):  # noqa: F811
    from app.services import location_report as lr
    seen = {}

    def fake(lat, lon, wait_s=4.0):
        seen[(round(lat), round(lon))] = 1
        return _bio_near(lat, lon) if lat < 0 else {"available": False, "status": "unavailable", "message": "none"}
    monkeypatch.setattr(lr.obis_service, "location_biodiversity", fake)
    a, b = report(client, h, -10, 122).json(), report(client, h, 30, 150).json()
    assert a["obis"]["available"] and b["obis"]["available"] is False and len(seen) == 2


def test_a_dense_cluster_is_flagged_so_a_record_share_is_not_read_as_a_regional_share(db_session):
    inp = inputs(anom=1.5, forecast=1.4)
    hw = np.zeros((4, 4), dtype=bool)
    hw[0, 0] = True                                                            # one cell is inside the heatwave
    recs = [[0, 0, "Bay fish", "2026-01-01", None]] * 90 + [[3, 3, "Open fish", "2026-01-01", None]] * 5 + [[2, 3, "Other fish", "2026-01-01", None]] * 5
    o = bv.overlaps(recs, inp, hw, None)
    assert o["heatwave"]["share_pct"] == 90.0 and o["heatwave"]["cells_share_pct"] == pytest.approx(33.3, abs=0.1) and o["heatwave"]["species_share_pct"] == pytest.approx(33.3, abs=0.1)
    assert o["densest_cell_share_pct"] == 90.0
    bio = {"available": True, "status": "cached", "scope": "nearby", "half_width_deg": 2.0, "historical": False, "window_start": "2024-10-28", "records_in_box": 100, "records_all_time": 100, "sampled_records": 100, "taxa": 3,
           "trail": [], "fetched_at": "2026-10-27T10:00:00+00:00", "api": "u", "species": [{"scientific_name": "Bay fish", "aphia_id": None, "group": "Teleostei", "category": None, "records": 90, "sampled_records": 90, "nearest_km": 1, "latest_record": "2026-01-01", "datasets": []}],
           "records": recs}
    v = bv.view(db_session, bio, 0.0, inp, hw, today=TODAY)
    assert "Caution: 90% of the matched records come from one 0.25° grid cell" in v["exposure_text"] and "recorded grid cells" in v["exposure_text"]


def test_no_overlap_is_stated_in_words_not_as_zero_species(db_session):
    inp = inputs(anom=0.2, forecast=0.1)
    hw = np.zeros((4, 4), dtype=bool)
    recs = [[0, 0, "A", "2026-01-01", None], [3, 3, "B", "2026-01-02", None]]
    bio = {"available": True, "status": "cached", "scope": "nearby", "half_width_deg": 5.0, "historical": False, "window_start": "2024-10-28", "records_in_box": 2, "records_all_time": 2, "sampled_records": 2, "taxa": 2,
           "trail": [], "fetched_at": "2026-10-27T10:00:00+00:00", "api": "u", "species": [{"scientific_name": "A", "aphia_id": None, "group": "T", "category": None, "records": 1, "sampled_records": 1, "nearest_km": 1, "latest_record": "2026-01-01", "datasets": []}],
           "records": recs}
    t = bv.view(db_session, bio, 0.0, inp, hw, today=TODAY)["exposure_text"]
    assert "None of the 2 recorded species has records inside the current marine-heatwave footprint" in t and "no recorded species has records where the model predicts" in t
    assert "0 species" not in t and "0 of" not in t


def test_near_normal_forecast_text_never_prints_negative_zero():
    from app.services import forecast_reading as fr
    r = fr.reading(20.0, -0.04, [19.95] * 7, [-0.04, -0.03, -0.02, -0.01, 0.0, -0.01, -0.04])
    assert "-0.0 " not in r["text"] and "close to normal" in r["text"]


def test_a_failed_refresh_never_returns_an_old_file_labelled_live(monkeypatch):
    monkeypatch.setattr(ctx, "ENABLED", True)
    monkeypatch.setattr(ctx, "build", lambda lat, lon: {"schema": ctx.SCHEMA, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "chlorophyll": {"available": True}, "currents": None, "errors": []})
    assert ctx.location_context(0.0, 0.0, wait_s=5)["status"] == "live"
    f = ctx._file(ctx._key(0.0, 0.0))
    old = ctx.json.loads(f.read_text())
    old["fetched_at"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat(timespec="seconds")
    f.write_text(ctx.json.dumps(old))
    monkeypatch.setattr(ctx, "build", lambda lat, lon: (_ for _ in ()).throw(RuntimeError("down")))
    assert ctx.location_context(0.0, 0.0, wait_s=5)["status"] == "stale_cache"
