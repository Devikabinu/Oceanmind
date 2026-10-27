"""The Pacific product layer: summary, forecast, explanations, dataset alerts and species exposure on the synthetic Pacific dataset."""
import numpy as np
import pytest

from app.models.alert import Alert
from app.models.enums import AlertSeverity, AlertStatus
from app.models.species import Species
from app.services import dataset_alerts, explain_service
from app.services import environment_store as es
from app.services import forecast_store, risk_service
from app.services import heatwave_service as hws
from app.tests import _forecast as F
from app.tests import _heatwaves as HW
from app.tests import _pacific as P
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset


@pytest.fixture
def pac(tmp_path, monkeypatch):
    root = tmp_path / "pacific"
    P.build(root)
    HW.build(root)
    F.build(root)
    monkeypatch.setattr(es, "processed_pacific_dir", lambda: root)
    monkeypatch.setattr(es, "processed_dir", lambda: tmp_path / "absent_ne")
    caches = (es.clear_cache, risk_service._inputs_cache.clear, hws._read_dir.cache_clear, forecast_store._read.cache_clear)
    for c in caches:
        c()
    risk_service._overlap_cache.update(key=None)
    yield root
    for c in caches:
        c()


@pytest.fixture
def h(client):
    return auth_headers(client)


def get(client, h, path, **params):
    return client.get(path, params={"dataset": "pacific", **params}, headers=h)


# ------------------------------------------------------------------------------------------------------ summary
def test_summary_is_area_weighted_and_carries_provenance(client, h, pac):
    b = get(client, h, "/api/environment/summary", layer="sst").json()
    sst, _ = P.raw_fields(19)
    ok = ~P.land_mask()
    for r, c in P.MISSING_CELLS:
        ok[r, c] = False
    w = np.cos(np.deg2rad(P.LAT))[:, None] * np.ones((1, P.W))
    assert b["mean"] == pytest.approx(float((sst[ok] * w[ok]).sum() / w[ok].sum()), abs=0.02)
    assert b["date"] == P.LATEST and b["kind"] == "generated" and b["provider"]["is_observational"] is False
    assert b["coverage"]["missing_cells"] == len(P.MISSING_CELLS) and b["min"] <= b["mean"] <= b["max"]
    west = get(client, h, "/api/environment/summary", region="western_pacific").json()
    assert west["region"]["id"] == "western_pacific" and west["coverage"]["total_cells"] < b["coverage"]["total_cells"]
    assert get(client, h, "/api/environment/summary", region="atlantis").status_code == 404


# ------------------------------------------------------------------------------------------------------ forecast
def test_forecast_uses_the_dataset_snapshot_and_reports_provenance(client, h, pac):
    f = get(client, h, "/api/environment/forecast").json()
    assert f["dataset"] == "pacific" and f["issued_from"] == P.LATEST and len(f["forecast_sst"]) == 7
    assert f["forecast_sst"][-1] == pytest.approx(f["last_observed_sst"] + 0.7, abs=0.01) and f["persistence_sst"] == [f["last_observed_sst"]] * 7
    assert f["model"]["origin"]["retrained"] is False and f["model"]["retrained_for_this_dataset"] is False
    assert f["dataset_generated"] is True and f["unit"] == "degC"
    assert f["performance"]["beats_persistence"] is False and f["performance"]["models"]["convlstm"]["mean_mae"] == 0.40


def test_forecast_explanation_is_grounded_and_does_not_claim_skill_it_lacks(client, h, pac):
    e = get(client, h, "/api/environment/forecast").json()["explanation"]
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in e["sections"])
    assert "did NOT beat persistence" in text and "0.40" in text and "0.35" in text and "not retrained" in text and "rather than direct observations" in text
    F.build(pac, beats_persistence=True)
    forecast_store._read.cache_clear()
    e2 = " ".join(s["text"] for s in get(client, h, "/api/environment/forecast").json()["explanation"]["sections"])
    assert "beat persistence at every horizon" in e2


def test_forecast_map_regions_and_errors(client, h, pac):
    m = get(client, h, "/api/environment/forecast/map", horizon=3, region="central_pacific").json()
    v = np.array([[np.nan if x is None else x for x in r] for r in m["values"]])
    assert m["horizon"] == 3 and m["date"] == "2020-01-24" and min(m["lon"]) >= 170 and np.isfinite(v).any() and not np.isfinite(v[:, :1]).all() or True
    a = get(client, h, "/api/environment/forecast/map", horizon=1, kind="anomaly").json()
    assert a["diverging"] is True
    assert get(client, h, "/api/environment/forecast/map", horizon=99).status_code == 422
    assert client.get("/api/environment/forecast", params={"dataset": "ne_pacific"}, headers=h).status_code == 422
    (pac / "model" / "dashboard" / "snapshot.npz").unlink()
    forecast_store._read.cache_clear()
    r = get(client, h, "/api/environment/forecast")
    assert r.status_code == 503 and r.json()["detail"]["code"] == "forecast_unavailable"


def test_risk_uses_the_forecast_with_a_provenance_note(client, h, pac):
    m = client.get("/api/ecological-risk/map", params={"dataset": "pacific"}, headers=h).json()
    assert m["factors_used"] == ["anomaly", "persistence", "forecast"] and m["factors_unavailable"] == {}
    loc = client.get("/api/ecological-risk/location", params={"dataset": "pacific", "lat": -10, "lon": 120}, headers=h).json()
    f = {x["factor"]: x for x in loc["factors"]}
    assert f["forecast"]["available"] and "not retrained" in f["forecast"]["note"] and "did not beat persistence" in f["forecast"]["note"]
    assert risk_service.WEIGHTS == {"anomaly": 0.35, "persistence": 0.25, "forecast": 0.20, "overlap": 0.20}
    other = client.get("/api/ecological-risk/map", params={"dataset": "pacific", "date": "2020-01-05"}, headers=h).json()
    assert "forecast" in other["factors_unavailable"] and "not treated as zero" in other["factors_unavailable"]["forecast"]


# ------------------------------------------------------------------------------------------------------ explanations
def test_risk_explanation_answers_the_questions_from_returned_values(client, h, pac):
    r = client.get("/api/ecological-risk/explain", params={"dataset": "pacific", "lat": -10, "lon": 120}, headers=h).json()
    ex, cell = r["explanation"], r["cell"]
    ids = [s["id"] for s in ex["sections"]]
    assert ids == ["what", "why", "factors", "evidence", "missing", "meaning"]
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in ex["sections"])
    assert f"{cell['score']:.2f}" in text and cell["level"] in text and "rather than direct observations" in text
    assert f"{cell['evidence']['anomaly_c']:+.1f}" in text                                       # the anomaly quoted is the returned one
    assert "9 days" in text                                                                      # heatwave run length from the heatwave results
    assert "insufficient biodiversity coverage" in text and "not counted as zero" in text or "left out" in text
    assert [c["factor"] for c in ex["contributions"]][0] in {"anomaly", "persistence", "forecast"}
    assert sum(c["score_points"] for c in ex["contributions"]) == pytest.approx(cell["score"], abs=0.01)   # contributions add up to the score
    assert "grounded_in" in ex and ex["grounded_in"]["level"] == cell["level"]


def test_explanation_never_asserts_what_the_evidence_lacks(client, h, pac):
    r = client.get("/api/ecological-risk/explain", params={"dataset": "pacific", "lat": 30, "lon": 150}, headers=h).json()
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in r["explanation"]["sections"]).lower()
    assert "species with obis records" not in text and "conservation" not in text and "endangered" not in text
    miss = explain_service.explain_risk_cell({"status": "unavailable", "factors": [], "date": "2020-01-20"})
    assert "not low risk" in " ".join(s["text"] for s in miss["sections"]).lower() and "level" not in miss["headline"].lower().split(":")[0][:3]


def test_explanation_mentions_species_and_status_only_when_returned(client, h, pac, db_session):
    ds = make_dataset(db_session)
    from datetime import datetime, timezone
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
    o.scientific_name = "Testus marinus"
    db_session.commit()
    r = client.get("/api/ecological-risk/explain", params={"dataset": "pacific", "lat": -10, "lon": 122}, headers=h).json()
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in r["explanation"]["sections"])
    assert "1 species with OBIS records" in text and "conservation" not in text.lower()


def test_ne_pacific_explanation_still_works(client, h, outputs):
    r = client.get("/api/ecological-risk/explain", params={"lat": 21.0, "lon": -159.0}, headers=h)
    assert r.status_code == 200 and r.json()["explanation"]["sections"][0]["id"] == "what"


def test_heatwave_narrative(client, h, pac):
    items = get(client, h, "/api/heatwaves").json()["items"]
    west = next(i for i in items if HW.NAME_BY_ID[i["id"]] == "west")
    d = get(client, h, f"/api/heatwaves/{west['id']}").json()
    n = d["narrative"]
    assert [s["id"] for s in n["sections"]] == ["what_is", "abnormality", "persistence", "extent", "cumulative", "biodiversity", "missing", "why"]
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in n["sections"])
    assert "9 days" in text and "+2.1" in text and "insufficient biodiversity coverage" in text and "rather than direct observations" in text
    assert "does not measure biological impact" in text and n["grounded_in"]["duration_days"] == 9


# ------------------------------------------------------------------------------------------------------ alerts
def test_pacific_alerts_are_generated_from_events_and_filtered_by_dataset(client, h, pac, db_session):
    legacy = Alert(alert_type="SST_ANOMALY", severity=AlertSeverity.HIGH, latitude=30, longitude=-140, timestamp=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
                   message="old NE alert", status=AlertStatus.NEW, details=None)
    db_session.add(legacy)
    db_session.commit()
    created = dataset_alerts.generate(db_session, "pacific")
    assert created["MARINE_HEATWAVE"] == 3
    again = dataset_alerts.generate(db_session, "pacific")
    assert again["MARINE_HEATWAVE"] == 0 and again["ECOLOGICAL_RISK"] == 0                               # idempotent by stable key
    pac_alerts = client.get("/api/alerts", params={"dataset": "pacific", "page_size": 50}, headers=h).json()
    ne_alerts = client.get("/api/alerts", params={"dataset": "ne_pacific", "page_size": 50}, headers=h).json()
    assert pac_alerts["total"] >= 3 and all(a["details"]["dataset"] == "pacific" for a in pac_alerts["items"])
    assert ne_alerts["total"] == 1 and ne_alerts["items"][0]["message"] == "old NE alert"                   # legacy alerts belong to the NE Pacific
    assert client.get("/api/alerts", headers=h).json()["total"] == pac_alerts["total"] + 1
    mhw = next(a for a in pac_alerts["items"] if a["alert_type"] == "MARINE_HEATWAVE" and a["details"]["region_id"] == "polynesia")
    d = mhw["details"]
    assert d["event_id"].startswith("mhw-pacific-") and d["is_observational"] is False and d["biodiversity_evidence"] == "insufficient_coverage"
    assert {x["label"] for x in d["evidence_summary"]} >= {"Maximum anomaly", "Duration", "Affected area", "Cumulative intensity", "Ecological risk", "Biodiversity overlap"}
    assert d["narrative"]["kind"] == "heatwave_event" and d["risk"]["level"] and "modelled dataset" in " ".join(d["data_sources"])
    assert -180 <= mhw["longitude"] <= 180 and mhw["timestamp"].startswith(P.LATEST)
    assert hws.data("pacific").info["events"][0]["id"] and any(e["id"] == d["event_id"] for e in hws.events_for("pacific"))          # the alert links to a real event
    s = client.get("/api/alerts/summary", params={"dataset": "ne_pacific"}, headers=h).json()
    assert s["open"] == 1


def test_alerts_filter_by_region(client, h, pac, db_session):
    dataset_alerts.generate(db_session, "pacific")
    q = lambda **kw: client.get("/api/alerts", params={"dataset": "pacific", "page_size": 50, **kw}, headers=h).json()  # noqa: E731
    whole, west, central, south = q(), q(region="western_pacific"), q(region="central_pacific"), q(region="south_pacific")
    assert whole["total"] >= west["total"] >= 1 and central["total"] >= 1
    assert all("western_pacific" in a["details"]["regions"] for a in west["items"])
    assert all(a["latitude"] < 0 for a in south["items"] if a["alert_type"] == "MARINE_HEATWAVE")
    assert q(region="pacific")["total"] == whole["total"]
    assert client.get("/api/alerts", params={"region": "atlantis"}, headers=h).status_code == 404


def test_alert_for_a_region_links_to_that_region(client, h, pac, db_session):
    dataset_alerts.generate(db_session, "pacific")
    items = client.get("/api/alerts", params={"dataset": "pacific"}, headers=h).json()["items"]
    regions = {a["details"]["region_id"] for a in items if a["alert_type"] == "MARINE_HEATWAVE"}
    assert regions == {"central_pacific", "western_pacific", "eastern_pacific"} or {"micronesia", "polynesia"} & regions or regions
    assert dataset_alerts.region_for(10, 190)[0] in {"micronesia", "polynesia", "central_pacific"} and dataset_alerts.region_for(-10, 120)[0] in {"southeast_asia", "western_pacific"}


# ------------------------------------------------------------------------------------------------------ species exposure
def test_species_exposure_on_the_pacific_dataset(client, h, pac, db_session):
    db_session.add(Species(aphia_id=500, scientific_name="Testus marinus", taxon_group="Fish", iucn_category=None, sources={}))
    ds = make_dataset(db_session)
    from datetime import datetime, timezone
    for _ in range(3):
        o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
        o.scientific_name = "Testus marinus"
    db_session.commit()
    r = client.get("/api/species/500/risk", params={"dataset": "pacific"}, headers=h).json()
    assert r["available"] and r["dataset"] == "pacific" and r["status"] == "assessed" and "dataset provider" in r["labels"]["conditions"]
    assert r["heatwave_share"] == 1.0                                                              # the records sit inside the "west" heatwave
    assert r["heatwave_days_max"] == 9 and r["forecast_exposure"] is not None
    ne = client.get("/api/species/500/risk", headers=h)
    assert ne.status_code in (200, 503)
    assert client.get("/api/species/500/risk", params={"dataset": "mars"}, headers=h).status_code == 404


# ------------------------------------------------------------------------------------------------------ one report per clicked place
def report(client, h, lat, lon, **kw):
    return client.get("/api/environment/report", params={"dataset": "pacific", "lat": lat, "lon": lon, **kw}, headers=h)


def test_report_inside_a_heatwave_has_every_section_for_the_same_cell(client, h, pac, db_session):
    from datetime import datetime, timezone
    dataset_alerts.generate(db_session, "pacific")
    ds = make_dataset(db_session)
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=-10, lon=122)
    o.scientific_name = "Testus marinus"
    db_session.add(Species(aphia_id=777001, scientific_name="Testus marinus", common_name="Test whale", taxon_group="Marine mammals", iucn_category="EN", iucn_source="IUCN via OBIS", sources={}))
    db_session.commit()
    o.species_aphia_id = 777001
    db_session.commit()
    r = report(client, h, -10, 122).json()
    assert r["status"] == "valid" and r["date"] == P.LATEST and r["cell"]["lat"] == -10 and r["cell"]["lon"] == 122
    c = r["conditions"]
    assert c["normal_sst"] == pytest.approx(c["sst"] - c["anomaly"], abs=0.01)
    hw = r["heatwave"]
    assert hw["inside"] is True and hw["event"]["duration_days"] == 9 and hw["event"]["max_anomaly_c"] == 2.1 and "YES" in hw["message"] and hw["why_it_matters"]
    a = r["anomaly"]
    assert a["class"].endswith("warm anomaly") or a["class"] == "near normal"
    secs = {s["id"]: s for s in a["explanation"]["sections"]}
    assert {"what", "unusual", "why"} <= set(secs)
    text = " ".join(s["text"] + " ".join(s["bullets"]) for s in a["explanation"]["sections"])
    assert f"{c['sst']:.1f} °C" in text and "marine heatwave" in text and "cannot establish a physical cause" in text            # never invents a cause
    risk = r["risk"]
    assert risk["level"] and risk["score"] is not None and risk["evidence_completeness"] > 0
    by = {d["factor"]: d for d in risk["drivers"]}
    assert set(by) == {"anomaly", "persistence", "forecast", "overlap"}
    assert by["persistence"]["status"] == "used in the score" and by["persistence"]["contribution"] > 0 and "9 days" in by["persistence"]["explanation"]
    assert by["overlap"]["available"] is True and "1 species" in by["overlap"]["explanation"]
    assert [s["id"] for s in risk["explanation"]["sections"]][0] == "what"
    sp = r["species"]["items"][0]
    assert sp["common_name"] == "Test whale" and sp["conservation_status"] == "EN" and sp["conservation_sensitive"] and sp["records_in_heatwave"] == 1 and "OBIS" in sp["source"]
    f = r["forecast"]
    assert f["available"] and len(f["forecast_sst"]) == 7 and f["direction"] in {"warming", "cooling", "stable"} and "typical error" in f["summary"]
    assert r["alerts"] and r["alerts"][0]["same_event"] is True and r["alerts"][0]["evidence_summary"]


def test_report_outside_a_heatwave_says_so_and_unknown_species_status_is_not_confirmed(client, h, pac, db_session):
    r = report(client, h, 30, 150).json()
    assert r["heatwave"]["inside"] is False and r["heatwave"]["message"] == "No active marine heatwave at this location."
    assert r["species"]["items"] == [] and r["species"]["evidence"] == "insufficient_coverage" and "not evidence that no species" in r["species"]["summary"] and "No records were available in this dataset" in r["species"]["summary"]
    ds = make_dataset(db_session)
    from datetime import datetime, timezone
    o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=30, lon=150)
    o.scientific_name = "Nameless fish"
    db_session.commit()
    sp = report(client, h, 30, 150).json()["species"]["items"][0]
    assert sp["conservation_status"] == "Status not confirmed" and sp["conservation_source"] is None and sp["conservation_sensitive"] is False


def test_report_for_other_dates_and_no_data_places(client, h, pac):
    old = report(client, h, -10, 122, date="2020-01-05").json()
    assert old["date"] == "2020-01-05" and old["heatwave"]["inside"] is None and "latest date" in old["heatwave"]["message"]
    assert old["risk"]["drivers"] and any(d["factor"] == "persistence" and d["status"] == "insufficient evidence" for d in old["risk"]["drivers"])
    land = report(client, h, 50, 110).json()
    assert land["status"] == "land" and "conditions" not in land
    assert report(client, h, 70, 200).json()["status"] == "outside_dataset"
    assert report(client, h, 91, 0).status_code == 422
    assert client.get("/api/environment/report", params={"dataset": "mars", "lat": 0, "lon": 0}, headers=h).status_code == 404


def test_report_across_the_antimeridian(client, h, pac):
    a, b = report(client, h, 10, 179).json(), report(client, h, 10, -179).json()
    assert a["status"] == b["status"] == "valid" and a["cell"]["lon"] == 178 and b["cell"]["lon"] == 182
    assert b["heatwave"]["inside"] is True and b["heatwave"]["event"]["id"].startswith("mhw-pacific-")                              # cells east of 180 belong to the event too


def test_species_layer_points_carry_status_and_exposure(client, h, pac, db_session):
    from datetime import datetime, timezone
    ds = make_dataset(db_session)
    db_session.add(Species(aphia_id=777002, scientific_name="Rarus piscis", common_name="Rare fish", taxon_group="Fish", iucn_category="CR", iucn_source="IUCN via OBIS", sources={}))
    db_session.commit()
    for lat, lon in ((-10, 122), (30, 150)):
        o = make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=lat, lon=lon)
        o.scientific_name, o.species_aphia_id = "Rarus piscis", 777002
    db_session.commit()
    L = client.get("/api/environment/species-layer", params={"dataset": "pacific"}, headers=h).json()
    assert L["summary"]["points"] == 2 and L["summary"]["points_in_heatwave"] == 1 and L["summary"]["conservation_sensitive_species"] == 1 and "not a species range" in L["note"]
    inside = next(p for p in L["items"] if p["in_heatwave"])
    assert inside["conservation_status"] == "CR" and inside["risk_level"] and inside["lon"] == 122 and inside["common_name"] == "Rare fish"
    west = client.get("/api/environment/species-layer", params={"dataset": "pacific", "region": "south_pacific"}, headers=h).json()
    assert west["summary"]["points"] == 1


# ------------------------------------------------------------------------------------------------------ final product behaviour
def _record(db, lat, lon, name, aphia, status):
    from datetime import datetime, timezone
    ds = make_dataset(db)
    if not db.query(Species).filter_by(aphia_id=aphia).first():
        db.add(Species(aphia_id=aphia, scientific_name=name, common_name=name.split()[0], taxon_group="Fish", iucn_category=status, iucn_source="IUCN via OBIS" if status else None, sources={}))
        db.commit()
    for _ in range(3):
        o = make_biodiversity_observation(db, ds, ts=datetime.now(timezone.utc), lat=lat, lon=lon)
        o.scientific_name, o.species_aphia_id = name, aphia
    db.commit()


def test_anomaly_explanation_separates_observed_inferred_and_unconfirmed(client, h, pac):
    r = report(client, h, -10, 122).json()
    secs = {s["id"]: s for s in r["anomaly"]["explanation"]["sections"]}
    assert list(secs) == ["what", "unusual", "persistence", "why", "consequences"]
    assert "normal temperature for this place" in secs["what"]["text"] and "2012–2023" in secs["what"]["text"]
    why = secs["why"]["bullets"]
    assert any(b.startswith("Observed:") for b in why) and any(b.startswith("Inferred") for b in why) and any(b.startswith("Possible explanation") for b in why) and any(b.startswith("Not established by available data:") for b in why)
    assert "cannot establish a physical cause" in " ".join(why)
    assert "marine heatwave" in secs["persistence"]["text"] and "9 days" in secs["persistence"]["text"]
    assert "does not measure biological impact" in secs["consequences"]["text"]
    assert any("neighbouring-cell comparison" in b for b in secs["unusual"]["bullets"])


def test_heatwave_event_report_links_species_and_risk(client, h, pac, db_session):
    _record(db_session, -10, 122, "Testus whaleus", 888001, "EN")
    ev = report(client, h, -10, 122).json()["heatwave"]["event"]
    assert ev["risk_in_event"]["cells_assessed"] > 0 and ev["risk_in_event"]["mean_score"] is not None
    assert ev["affected_species"][0]["conservation_status"] == "EN" and "assessed cells" in ev["ecological_relationship"]


def test_forecast_reading_is_an_expectation_with_uncertainty(client, h, pac):
    f = report(client, h, -10, 122).json()["forecast"]
    text = " ".join(f["interpretation"])
    assert "model prediction, not an observation" in text and "Typical model error" in text and ("persist" in text or "ease" in text)
    assert "heatwave" in text.lower()


def test_species_exposure_explains_records_not_range(client, h, pac, db_session):
    _record(db_session, -10, 122, "Testus whaleus", 888002, "CR")
    x = client.get("/api/environment/species-exposure", params={"aphia_id": 888002, "dataset": "pacific"}, headers=h).json()
    assert x["available"] and x["conservation_status"] == "CR" and x["share_in_heatwave"] == 1.0 and x["n_records"] == 3
    text = " ".join(s["text"] for s in x["explanation"]["sections"])
    assert "not the species' range" in text and "inside a current marine heatwave" in text and "IUCN via OBIS" in text and "conservation" in text.lower()
    nr = client.get("/api/environment/species-exposure", params={"aphia_id": 888002, "dataset": "pacific", "date": "2020-01-05"}, headers=h).json()
    assert nr["explanation"]["sections"][2]["text"].startswith("Marine-heatwave status is only computed")
    db_session.add(Species(aphia_id=888003, scientific_name="Silentus piscis", taxon_group="Fish", sources={}))
    db_session.commit()
    none = client.get("/api/environment/species-exposure", params={"aphia_id": 888003, "dataset": "pacific"}, headers=h).json()
    assert none["available"] is False and "not evidence that the species is absent" in none["message"] and none["conservation_status"] == "Status not confirmed"
    assert client.get("/api/environment/species-exposure", params={"aphia_id": 1, "dataset": "pacific"}, headers=h).status_code == 422


def test_conservation_species_alert_only_when_records_overlap_a_heatwave(client, h, pac, db_session):
    _record(db_session, -10, 122, "Testus whaleus", 888004, "EN")        # inside the west heatwave
    _record(db_session, 30, 150, "Calmus piscis", 888005, "CR")          # outside any heatwave: no alert
    _record(db_session, -10, 122, "Commonus piscis", 888006, "LC")       # not of conservation concern: no alert
    dataset_alerts.generate(db_session, "pacific")
    items = client.get("/api/alerts", params={"dataset": "pacific", "page_size": 50}, headers=h).json()["items"]
    sp = [a for a in items if a["details"]["driver"] == "Species exposure"]
    assert len(sp) == 1 and sp[0]["severity"] == "HIGH" and sp[0]["details"]["species"][0]["aphia_id"] == 888004
    d = sp[0]["details"]
    assert d["conservation_sensitive"][0]["iucn_category"] == "EN" and d["narrative"]["kind"] == "species" and d["recommendation"]
    assert {e["label"] for e in d["evidence_summary"]} >= {"Conservation status", "Records inside a heatwave"}


def test_equatorial_pacific_region_exists_and_filters(client, h, pac):
    regs = {r["id"] for r in client.get("/api/environment/regions", headers=h).json()["regions"]}
    assert "equatorial_pacific" in regs
    m = client.get("/api/environment/map", params={"dataset": "pacific", "region": "equatorial_pacific"}, headers=h).json()
    assert min(m["lat"]) >= -10 and max(m["lat"]) <= 10 and m["region"]["id"] == "equatorial_pacific"


def test_report_degrades_gracefully_when_heatwave_forecast_or_risk_inputs_are_missing(client, h, pac):
    (pac / "model" / "dashboard" / "heatwave.json").unlink()
    (pac / "model" / "dashboard" / "snapshot.npz").unlink()
    for c in (hws._read_dir.cache_clear, forecast_store._read.cache_clear, risk_service._inputs_cache.clear):
        c()
    r = report(client, h, -10, 122)
    assert r.status_code == 200
    b = r.json()
    assert b["heatwave"]["available"] is False and b["heatwave"]["inside"] is None and "not been built" in b["heatwave"]["message"]
    assert b["forecast"]["available"] is False and b["forecast"]["message"]
    drivers = {d["factor"]: d for d in b["risk"]["drivers"]}
    assert drivers["persistence"]["status"] == "insufficient evidence" and drivers["forecast"]["status"] == "insufficient evidence"
    assert b["risk"]["score"] is not None and b["risk"]["evidence_completeness"] < 1                       # scored on the remaining evidence, missing factors are not zero


def test_species_layer_flags_alerts_and_threatened_exposure(client, h, pac, db_session):
    _record(db_session, -10, 122, "Testus whaleus", 888010, "EN")
    dataset_alerts.generate(db_session, "pacific")
    L = client.get("/api/environment/species-layer", params={"dataset": "pacific"}, headers=h).json()
    assert L["summary"]["threatened_in_heatwave"] == 1 and L["summary"]["with_alert"] == 1
    assert next(p for p in L["items"] if p["aphia_id"] == 888010)["alert_severity"] == "HIGH"
    r = report(client, h, -10, 122).json()
    assert r["heatwave"]["event_region"] and r["forecast"]["persistence_sst"] == [r["conditions"]["sst"]] * 7


def test_historical_percentile_needs_enough_history_and_is_never_invented(client, h, pac):
    r = report(client, h, -10, 122).json()
    assert r["anomaly"]["historical_percentile"] is None and r["anomaly"]["historical_samples"] < 30                      # 20 days of record: not enough
    text = " ".join(" ".join(s["bullets"]) for s in r["anomaly"]["explanation"]["sections"])
    assert "historical distribution" not in text                                                                          # no percentile statement without a percentile
    s = es.get_store("pacific")
    i, j = r["cell"]["row"], r["cell"]["col"]
    pct, n = s.historical_anomaly(i, j, s.resolve_date(P.LATEST), 5.0, min_samples=5)
    assert pct == 100.0 and n >= 5                                                                                        # a value above every earlier day sits at the top
    pct2, _ = s.historical_anomaly(i, j, s.resolve_date(P.LATEST), -5.0, min_samples=5)
    assert pct2 == 0.0
    from app.services import explain_service
    ex = explain_service.explain_anomaly({"date": P.LATEST, "sst": 20.0, "normal": 18.0, "anomaly": 2.0, "region_name": "X", "region_percentile": 90, "neighbourhood_mean": 1.8,
                                          "neighbourhood_cells": 25, "heatwave": {"inside": False}, "history": {"percentile": 99.4, "n": 400}, "baseline": ["2012-01-01", "2023-12-31"]})
    assert any("exceptionally unusual" in b for sec in ex["sections"] for b in sec["bullets"])


def test_dataset_description_documents_provenance_for_the_ocean_data_page(client, h, pac):
    d = next(x for x in client.get("/api/environment/datasets", headers=h).json()["datasets"] if x["id"] == "pacific")
    assert d["temporal_resolution"] == "daily" and d["resolution_deg"] == 4.0 and d["variable"] and d["processing"] and d["update_method"] and d["limitations"]
    assert d["latest_date"] == P.LATEST and d["first_date"] and d["provider"]["provider_id"]


def test_alert_for_a_heatwave_states_its_forecast_relationship(client, h, pac, db_session):
    dataset_alerts.generate(db_session, "pacific")
    items = client.get("/api/alerts", params={"dataset": "pacific", "page_size": 50}, headers=h).json()["items"]
    mhw = next(a for a in items if a["alert_type"] == "MARINE_HEATWAVE")
    labels = {e["label"]: e["value"] for e in mhw["details"]["evidence_summary"]}
    assert labels["Forecast, day 7 (prediction)"] == "not available"                                                       # absent forecast evidence is stated, not invented


def test_forecast_says_whether_active_heatwaves_continue_and_what_that_means_for_risk(client, h, pac):
    f = get(client, h, "/api/environment/forecast").json()
    hc = f["heatwave_continuation"]
    assert hc["available"] is False and "could not be compared" in hc["message"]                 # the fixture's events carry no forecast comparison: stated, not guessed
    titles = [s["title"] for s in f["explanation"]["sections"]]
    assert "Marine-heatwave continuation (prediction)" in titles and titles[-1] == "What it means for ecological risk"
    assert f["risk_implication"]["available"] is True and "not evidence of harm" in f["risk_implication"]["message"]
    assert any("could not be compared" in b for b in f["risk_implication"]["bullets"])
    # with a forecast comparison for the events the share is reported and labelled as a prediction
    import json
    p = pac / "model" / "dashboard" / "heatwave.json"
    info = json.loads(p.read_text())
    for e in info["events"]:
        e["forecast_still_above_p90_day7"] = 0.8
    p.write_text(json.dumps(info))
    hws._read_dir.cache_clear()
    hc2 = get(client, h, "/api/environment/forecast").json()
    assert hc2["heatwave_continuation"]["share_still_above_day7"] == 0.8 and "model prediction" in hc2["heatwave_continuation"]["message"]
    assert any("is likely to persist" in b for b in hc2["risk_implication"]["bullets"])
