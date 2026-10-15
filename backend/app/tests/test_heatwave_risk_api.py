"""Marine heatwave, ecological risk and ocean coverage endpoints (synthetic export + real DB)."""
import pytest

from app.models.species import Species
from app.services import risk_service
from app.services.environment import env as load_env
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset, utc
from app.tests._outputs import LAT0, LON0


def test_heatwave_endpoints_require_auth(client):
    for path in ("/api/heatwaves", "/api/heatwaves/timeseries", "/api/ecological-risk/methodology", "/api/ocean/regions", "/api/ocean/coverage"):
        assert client.get(path).status_code == 401, path


def test_heatwave_list_filters_and_labels_method(client, outputs):
    h = auth_headers(client)
    body = client.get("/api/heatwaves", headers=h).json()
    assert body["total"] == 1
    assert body["summary"]["method"] == "test method"
    ev = body["items"][0]
    assert ev["status"] == "ACTIVE" and ev["duration_days"] == 11 and ev["category_name"].startswith("II")
    assert client.get("/api/heatwaves?min_category=3", headers=h).json()["total"] == 0
    assert client.get("/api/heatwaves?min_area_km2=999999", headers=h).json()["total"] == 0
    assert client.get("/api/heatwaves?min_category=9", headers=h).status_code == 422


def test_heatwave_detail_has_explanation_and_species_overlap(client, outputs, db_session):
    h = auth_headers(client)
    ds = make_dataset(db_session)
    # inside the event bbox (lat 20-22, lon -159.5..-158) and recent
    from datetime import datetime, timezone
    make_biodiversity_observation(db_session, ds, ts=datetime.now(timezone.utc), lat=21.0, lon=-159.0)
    db_session.commit()
    eid = client.get("/api/heatwaves", headers=h).json()["items"][0]["id"]
    d = client.get(f"/api/heatwaves/{eid}", headers=h).json()
    assert len(d["explanation"]) >= 3 and any("90th percentile" in s for s in d["explanation"])
    assert d["species_in_area"] and d["species_in_area"][0]["n_records"] == 1
    assert client.get("/api/heatwaves/nope", headers=h).status_code == 404


def test_heatwave_timeseries_bounds(client, outputs):
    h = auth_headers(client)
    ts = client.get("/api/heatwaves/timeseries?days=10", headers=h).json()
    assert len(ts["dates"]) == 10 == len(ts["heatwave_area_km2"])
    assert client.get("/api/heatwaves/timeseries?days=1", headers=h).status_code == 422


def test_risk_methodology_documents_weights_and_limits(client):
    m = client.get("/api/ecological-risk/methodology", headers=auth_headers(client)).json()
    assert m["weights"]["anomaly"] + m["weights"]["persistence"] + m["weights"]["forecast"] + m["weights"]["overlap"] == pytest.approx(1.0)
    assert m["limitations"] and "not" in m["status"].lower()


def test_location_risk_is_explainable_and_respects_coverage(client, outputs):
    h = auth_headers(client)
    r = client.get("/api/ecological-risk/location?lat=21.0&lon=-159.0", headers=h).json()
    assert r["level"] in {"HIGH", "CRITICAL"} and r["reasons"]
    factors = {f["factor"]: f for f in r["factors"]}
    assert factors["anomaly"]["level"] == "HIGH" and factors["overlap"]["available"] is False  # no species rows loaded
    assert client.get("/api/ecological-risk/location?lat=-30&lon=20", headers=h).status_code == 404
    assert client.get("/api/ecological-risk/location?lat=21.0&lon=-159.9", headers=h).status_code == 404  # land


def test_risk_areas_filter_by_level(client, outputs):
    h = auth_headers(client)
    high = client.get("/api/ecological-risk/areas?min_level=HIGH", headers=h).json()
    assert high["total"] >= 1 and all(i["level"] in {"HIGH", "CRITICAL"} for i in high["items"])
    assert client.get("/api/ecological-risk/areas?min_level=BOGUS", headers=h).status_code == 422


def test_risk_calculation_levels_and_overlap_weighting(outputs, db_session):
    assert [risk_service.level_for(s) for s in (0.0, 0.24, 0.25, 0.5, 0.75, 1.0)] == ["LOW", "LOW", "MEDIUM", "HIGH", "CRITICAL", "CRITICAL"]
    e = load_env()
    base = risk_service.factor_grids(e, None)
    assert base["used"] == ["anomaly", "persistence", "forecast"]
    i, j = 3, 4  # inside the heatwave block: anomaly 4 degC -> 1.0, run 10/14, forecast 4.5/3 -> 1.0
    assert base["factors"]["anomaly"][i, j] == pytest.approx(1.0)
    assert base["factors"]["persistence"][i, j] == pytest.approx(10 / 14, abs=1e-3)
    expected = (0.35 * 1.0 + 0.25 * 10 / 14 + 0.20 * 1.0) / 0.80
    assert float(base["score"][i, j]) == pytest.approx(expected, abs=1e-3)
    with_overlap = risk_service.factor_grids(e, {(0, 0): 3})
    assert with_overlap["factors"]["overlap"][i, j] == pytest.approx(1.0) and with_overlap["factors"]["overlap"][12, 12] == 0.0


def test_species_assessment_unavailable_without_records(outputs, db_session):
    a = risk_service.species_assessment(db_session, load_env(), 12345, "Nonexistent species")
    assert a["available"] is False and "No available observations" in a["message"]


def test_species_assessment_with_real_shaped_records(outputs, db_session):
    from datetime import datetime, timezone
    ds = make_dataset(db_session)
    now = datetime.now(timezone.utc)
    for k in range(6):
        make_biodiversity_observation(db_session, ds, ts=now, lat=LAT0 + 0.25 * (k % 3) + 0.5, lon=LON0 + 0.25 * k + 0.5)
    db_session.commit()
    a = risk_service.species_assessment(db_session, load_env(), -1, "Thunnus albacares")
    assert a["available"] and a["n_records"] == 6 and 0 <= a["score"] <= 1
    assert {f["factor"] for f in a["factors"]} == {"anomaly", "persistence", "forecast", "overlap"}
    assert any("OBIS records" in r for r in a["reasons"])


def test_ocean_regions_distinguish_covered_basin(client, outputs):
    regions = {r["id"]: r for r in client.get("/api/ocean/regions", headers=auth_headers(client)).json()["regions"]}
    assert regions["north_pacific"]["project_data"] == "partial"
    for other in ("south_atlantic", "indian", "arctic", "southern", "north_atlantic", "south_pacific"):
        assert regions[other]["project_data"] == "none", other


def test_ocean_coverage_lists_sources_without_claiming_global_data(client, outputs):
    items = {i["id"]: i for i in client.get("/api/ocean/coverage", headers=auth_headers(client)).json()["items"]}
    assert set(items) == {"noaa", "copernicus", "obis", "convlstm"}
    assert "Study region" in items["noaa"]["loaded_in_project"]
    assert "No records loaded" in items["obis"]["loaded_in_project"]
    assert items["convlstm"]["coverage_source"] == "Study region only"


def test_heatwave_summary_explains_the_method_and_disclaims_official_status(client, outputs):
    s = client.get("/api/heatwaves", headers=auth_headers(client)).json()["summary"]
    assert s["what_is"].startswith("A marine heatwave is a period")
    steps = " ".join(s["how_detected"]).lower()
    for word in ("baseline", "threshold", "consecutive", "intensity", "category"):
        assert word in steps
    assert "not an official" in steps


def test_heatwave_event_exposes_cumulative_intensity_and_timeline(client, outputs):
    h = auth_headers(client)
    ev = client.get("/api/heatwaves", headers=h).json()["items"][0]
    assert ev["cumulative_intensity_c_days"] == 44.0 and len(ev["timeline"]) == 11
    detail = client.get(f"/api/heatwaves/{ev['id']}", headers=h).json()
    assert any("degC-days" in line for line in detail["explanation"])


def test_risk_areas_region_filter(client, outputs):
    h = auth_headers(client)
    everywhere = client.get("/api/ecological-risk/areas?min_level=LOW&limit=200", headers=h).json()
    south = client.get("/api/ecological-risk/areas?min_level=LOW&limit=200&region=south", headers=h).json()
    north = client.get("/api/ecological-risk/areas?min_level=LOW&limit=200&region=north", headers=h).json()
    assert everywhere["total"] >= 1 and south["total"] == everywhere["total"] and north["total"] == 0  # synthetic grid sits at 20-24N
    assert client.get("/api/ecological-risk/areas?region=mars", headers=h).status_code == 422


def test_species_exposure_details(outputs, db_session):
    from datetime import datetime, timezone
    ds = make_dataset(db_session)
    now = datetime.now(timezone.utc)
    for k in range(8):  # inside the heatwave block (rows 0-7, cols 2-7 of the synthetic grid)
        make_biodiversity_observation(db_session, ds, ts=now, lat=LAT0 + 0.25 * (k % 4), lon=LON0 + 0.25 * (2 + k % 5))
    db_session.commit()
    a = risk_service.species_assessment(db_session, load_env(), -1, "Thunnus albacares")
    assert a["observed_locations"] == a["overlapping_locations"] > 0 and a["exposure_pct_locations"] == 100.0
    assert a["max_anomaly_c"] == 4.0 and a["mean_anomaly_c"] == 4.0
    assert a["heatwave_locations"] == a["observed_locations"] and a["heatwave_days_max"] == 10
    assert a["forecast_exposure"] == "HIGH" and a["forecast_mean_anomaly_c"] == 4.5
    assert a["recent_records_90d"] == 8 and a["latest_record"] == now.date().isoformat()


def test_unhandled_errors_are_generic_and_cors_safe(client):
    from fastapi.testclient import TestClient

    from app.main import app

    def boom():
        raise RuntimeError("secret internal detail /etc/passwd")

    app.add_api_route("/api/_boom", boom)
    try:
        r = TestClient(app, raise_server_exceptions=False).get("/api/_boom", headers={"Origin": "http://localhost:5173"})
    finally:
        app.router.routes.pop()
    assert r.status_code == 500 and "secret" not in r.text and "Traceback" not in r.text
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
