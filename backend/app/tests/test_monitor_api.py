"""Dashboard (/api/monitor) endpoints against the tiny synthetic export from _outputs.py."""
import pytest

from app.services import environment
from app.tests._helpers import auth_headers
from app.tests._outputs import H, N, W


def test_monitor_requires_auth(client):
    assert client.get("/api/monitor/overview").status_code == 401
    assert client.get("/api/monitor/location?lat=21&lon=-158").status_code == 401


def test_overview_is_interpretable_and_labels_data_age(client, outputs):
    o = client.get("/api/monitor/overview", headers=auth_headers(client)).json()
    assert o["data_status"]["observed_date"] == "2026-09-27"
    assert o["data_status"]["data_age_days"] >= 0
    assert o["improvement"]["better_all_horizons"] is True
    assert o["improvement"]["relative"] == pytest.approx(0.2)
    assert o["heatwave"]["n_events"] == 1
    assert o["risk"]["species_data_loaded"] is False  # no biodiversity rows in the test DB
    assert any("2012-2023 average" in s for s in o["interpretation"])
    assert set(o["provenance"]) == {"observed", "forecast", "evaluation", "derived"}


def test_performance(client, outputs):
    p = client.get("/api/monitor/performance", headers=auth_headers(client)).json()
    assert set(p["models"]) == {"convlstm", "persistence", "climatology"}
    assert p["training"] is None  # no training_history.json in the fixture


@pytest.mark.parametrize("layer", ["observed", "observed_anomaly", "forecast", "forecast_anomaly", "heatwave", "risk",
                                   "hindcast", "hindcast_truth", "hindcast_error"])
def test_every_map_layer_has_grid_and_coverage(client, outputs, layer):
    m = client.get(f"/api/monitor/map?layer={layer}&horizon=3", headers=auth_headers(client))
    assert m.status_code == 200, m.text
    body = m.json()
    assert len(body["values"]) == H and len(body["values"][0]) == W
    assert body["values"][0][0] is None  # land strip stays empty
    assert {"lat_min", "lat_max", "lon_min", "lon_max"} <= body["coverage"].keys()


def test_map_date_selection_and_validation(client, outputs):
    h = auth_headers(client)
    ok = client.get("/api/monitor/map?layer=observed_anomaly&date=2026-09-10", headers=h)
    assert ok.status_code == 200 and ok.json()["date"] == "2026-09-10"
    assert ok.json()["values"][5][5] == pytest.approx(1.0)  # history 15.0 vs climatology 14.0
    assert client.get("/api/monitor/map?layer=observed&date=2020-01-01", headers=h).status_code == 422  # outside history
    assert client.get("/api/monitor/map?layer=observed&date=garbage", headers=h).status_code == 422
    assert client.get("/api/monitor/map?layer=nope", headers=h).status_code == 422
    assert client.get("/api/monitor/map?layer=forecast&horizon=8", headers=h).status_code == 422


def test_location_inside_outside_and_land(client, outputs):
    h = auth_headers(client)
    inside = client.get("/api/monitor/location?lat=21.0&lon=-159.0", headers=h).json()
    assert inside["in_coverage"] and inside["is_ocean"]
    assert inside["observed"]["anomaly_c"] == pytest.approx(4.0)
    assert inside["heatwave"]["active"] is True
    assert inside["risk"]["level"] in {"MEDIUM", "HIGH", "CRITICAL"}
    assert inside["explanation"]
    assert client.get("/api/monitor/location?lat=21.0&lon=-159.9", headers=h).json()["is_ocean"] is False  # land strip
    far = client.get("/api/monitor/location?lat=-30&lon=20", headers=h).json()  # South Atlantic: no data here
    assert far["in_coverage"] is False and "Outside" in far["message"]
    assert client.get("/api/monitor/location?lat=95&lon=0", headers=h).status_code == 422


def test_history_and_point_respect_coverage(client, outputs):
    h = auth_headers(client)
    hist = client.get("/api/monitor/history?lat=21.0&lon=-158.5&days=14", headers=h).json()
    assert len(hist["series"]) == 14 and hist["series"][0]["anomaly"] == pytest.approx(1.0)
    assert client.get("/api/monitor/history?lat=-30&lon=20", headers=h).status_code == 404
    ok = client.get("/api/monitor/point?lat=20.125&lon=-158.875", headers=h)
    assert ok.status_code == 200 and len(ok.json()["forecast"]) == N and len(ok.json()["latest"]["forecast"]) == N
    assert client.get("/api/monitor/point?lat=20.125&lon=-159.875", headers=h).status_code == 404  # land
    assert client.get("/api/monitor/point?lat=0&lon=0", headers=h).status_code == 404  # outside grid


def test_hotspots_observed_and_forecast(client, outputs):
    h = auth_headers(client)
    obs = client.get("/api/monitor/hotspots?horizon=0&min_abs=1", headers=h).json()
    assert obs["kind"] == "observed" and obs["total"] >= 1
    top = obs["items"][0]
    assert top["severity"] == "CRITICAL" and top["direction"] == "warm"
    assert top["value_c"] - top["baseline_c"] == pytest.approx(top["mean_anomaly"], abs=0.05)
    assert top["persistence_days"] == 10
    fc = client.get("/api/monitor/hotspots?horizon=7&min_abs=2", headers=h).json()
    assert fc["kind"] == "forecast" and all(i["mean_anomaly"] >= 2 for i in fc["items"])
    assert client.get("/api/monitor/hotspots?horizon=9", headers=h).status_code == 422
    assert client.get("/api/monitor/hotspots?horizon=0&date=2026-09-05", headers=h).json()["date"] == "2026-09-05"


def test_missing_outputs_return_503_not_500(client, tmp_path, monkeypatch):
    monkeypatch.setattr(environment, "processed_dir", lambda: tmp_path)
    environment.clear_cache()
    h = auth_headers(client)
    for path in ("/api/monitor/overview", "/api/monitor/location?lat=21&lon=-158", "/api/heatwaves", "/api/ecological-risk/areas"):
        assert client.get(path, headers=h).status_code == 503, path
    environment.clear_cache()
