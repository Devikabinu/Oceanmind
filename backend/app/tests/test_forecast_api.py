import uuid

from app.tests._helpers import auth_headers, make_dataset, make_forecast, utc


def _seed(db_session):
    ds = make_dataset(db_session)
    make_forecast(db_session, ds, ts=utc(2026, 9, 1), lat=10, lon=75, horizon=1)
    make_forecast(db_session, ds, ts=utc(2026, 9, 5), lat=12, lon=72, horizon=7)
    make_forecast(db_session, ds, ts=utc(2026, 9, 9), lat=15, lon=77, horizon=14)


def test_list_forecasts_requires_auth(client):
    assert client.get("/api/forecast").status_code == 401
    assert client.get(f"/api/forecast/{uuid.uuid4()}").status_code == 401


def test_list_forecasts_paginated_shape_and_order(client, db_session):
    _seed(db_session)
    response = client.get("/api/forecast?page_size=2", headers=auth_headers(client))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3 and body["page"] == 1 and body["page_size"] == 2
    assert len(body["items"]) == 2
    # newest first
    assert body["items"][0]["forecast_horizon_days"] == 14
    assert {"id", "dataset_id", "predicted_sst", "model_version", "created_at"} <= body["items"][0].keys()

    page2 = client.get("/api/forecast?page_size=2&page=2", headers=auth_headers(client)).json()
    assert len(page2["items"]) == 1 and page2["total"] == 3


def test_list_forecasts_filters(client, db_session):
    _seed(db_session)
    headers = auth_headers(client)

    by_horizon = client.get("/api/forecast?forecast_horizon_days=7", headers=headers).json()
    assert [i["forecast_horizon_days"] for i in by_horizon["items"]] == [7]

    by_date = client.get(
        "/api/forecast?start_date=2026-09-02T00:00:00Z&end_date=2026-09-06T00:00:00Z", headers=headers
    ).json()
    assert by_date["total"] == 1

    by_bbox = client.get(
        "/api/forecast?min_latitude=11&max_latitude=16&min_longitude=71&max_longitude=78", headers=headers
    ).json()
    assert by_bbox["total"] == 2


def test_list_forecasts_bad_filters_422(client):
    headers = auth_headers(client)
    for query in [
        "min_latitude=95",
        "max_longitude=181",
        "min_latitude=20&max_latitude=10",
        "min_longitude=80&max_longitude=70",
        "start_date=2026-09-10T00:00:00Z&end_date=2026-09-01T00:00:00Z",
        "start_date=not-a-date",
        "forecast_horizon_days=0",
        "forecast_horizon_days=abc",
        "page=0",
        "page_size=501",
    ]:
        assert client.get(f"/api/forecast?{query}", headers=headers).status_code == 422, query


def test_get_forecast_by_id_and_404(client, db_session):
    ds = make_dataset(db_session)
    row = make_forecast(db_session, ds)
    headers = auth_headers(client)

    ok = client.get(f"/api/forecast/{row.id}", headers=headers)
    assert ok.status_code == 200
    assert ok.json()["id"] == str(row.id)
    assert ok.json()["predicted_sst"] == 29.5

    assert client.get(f"/api/forecast/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get("/api/forecast/not-a-uuid", headers=headers).status_code == 422
