import uuid

from app.tests._helpers import auth_headers, make_anomaly, make_dataset, make_ocean_observation, utc


def _seed(db_session):
    ds = make_dataset(db_session)
    o1 = make_ocean_observation(db_session, ds, ts=utc(2026, 6, 1), lat=10, lon=75)
    o2 = make_ocean_observation(db_session, ds, ts=utc(2026, 6, 10), lat=14, lon=71)
    o3 = make_ocean_observation(db_session, ds, ts=utc(2026, 6, 20), lat=9, lon=77)
    make_anomaly(db_session, o1, is_anomaly=True, score=0.9)
    make_anomaly(db_session, o2, is_anomaly=False, score=0.2)
    make_anomaly(db_session, o3, is_anomaly=True, score=0.8)


def test_anomaly_requires_auth(client):
    assert client.get("/api/anomaly").status_code == 401
    assert client.get(f"/api/anomaly/{uuid.uuid4()}").status_code == 401


def test_list_anomalies_paginated(client, db_session):
    _seed(db_session)
    body = client.get("/api/anomaly?page_size=2", headers=auth_headers(client)).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["items"][0]["timestamp"].startswith("2026-06-20")
    assert {"observation_id", "anomaly_score", "is_anomaly", "model_version"} <= body["items"][0].keys()


def test_list_anomalies_filters(client, db_session):
    _seed(db_session)
    headers = auth_headers(client)

    flagged = client.get("/api/anomaly?is_anomaly=true", headers=headers).json()
    assert flagged["total"] == 2 and all(i["is_anomaly"] for i in flagged["items"])

    normal = client.get("/api/anomaly?is_anomaly=false", headers=headers).json()
    assert normal["total"] == 1 and not normal["items"][0]["is_anomaly"]

    by_date = client.get(
        "/api/anomaly?start_date=2026-06-05T00:00:00Z&end_date=2026-06-15T00:00:00Z", headers=headers
    ).json()
    assert by_date["total"] == 1

    by_bbox = client.get(
        "/api/anomaly?min_latitude=9&max_latitude=10&min_longitude=74&max_longitude=78", headers=headers
    ).json()
    assert by_bbox["total"] == 2


def test_list_anomalies_bad_filters_422(client):
    headers = auth_headers(client)
    for query in [
        "is_anomaly=maybe",
        "min_latitude=-91",
        "min_latitude=20&max_latitude=10",
        "start_date=2026-06-10T00:00:00Z&end_date=2026-06-01T00:00:00Z",
        "page=-1",
    ]:
        assert client.get(f"/api/anomaly?{query}", headers=headers).status_code == 422, query


def test_get_anomaly_by_id_and_404(client, db_session):
    ds = make_dataset(db_session)
    row = make_anomaly(db_session, make_ocean_observation(db_session, ds))
    headers = auth_headers(client)

    ok = client.get(f"/api/anomaly/{row.id}", headers=headers)
    assert ok.status_code == 200 and ok.json()["id"] == str(row.id)
    assert client.get(f"/api/anomaly/{uuid.uuid4()}", headers=headers).status_code == 404
