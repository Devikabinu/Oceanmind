import uuid

from app.models.enums import DatasetKind, RiskLevel
from app.tests._helpers import auth_headers, make_biodiversity_observation, make_dataset, make_risk, utc


def _seed(db_session):
    ds = make_dataset(db_session, DatasetKind.BIODIVERSITY)
    o1 = make_biodiversity_observation(db_session, ds, ts=utc(2026, 3, 1), lat=10, lon=75)
    o2 = make_biodiversity_observation(db_session, ds, ts=utc(2026, 4, 1), lat=14, lon=71)
    o3 = make_biodiversity_observation(db_session, ds, ts=utc(2026, 5, 1), lat=9, lon=77)
    make_risk(db_session, o1, RiskLevel.LOW, 0.1)
    make_risk(db_session, o2, RiskLevel.CRITICAL, 0.9)
    make_risk(db_session, o3, RiskLevel.CRITICAL, 0.8)


def test_risk_requires_auth(client):
    assert client.get("/api/risk").status_code == 401
    assert client.get(f"/api/risk/{uuid.uuid4()}").status_code == 401


def test_list_risk_paginated(client, db_session):
    _seed(db_session)
    body = client.get("/api/risk?page_size=2", headers=auth_headers(client)).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["items"][0]["timestamp"].startswith("2026-05-01")
    assert body["items"][0]["contributing_factors"] == {"thermal_stress": 0.8}


def test_list_risk_filters(client, db_session):
    _seed(db_session)
    headers = auth_headers(client)

    critical = client.get("/api/risk?risk_level=CRITICAL", headers=headers).json()
    assert critical["total"] == 2 and all(i["risk_level"] == "CRITICAL" for i in critical["items"])

    by_date = client.get(
        "/api/risk?start_date=2026-03-15T00:00:00Z&end_date=2026-04-15T00:00:00Z", headers=headers
    ).json()
    assert by_date["total"] == 1

    by_bbox = client.get(
        "/api/risk?min_latitude=13&max_latitude=15&min_longitude=70&max_longitude=72", headers=headers
    ).json()
    assert by_bbox["total"] == 1


def test_list_risk_bad_filters_422(client):
    headers = auth_headers(client)
    for query in [
        "risk_level=EXTREME",
        "risk_level=low",
        "max_longitude=200",
        "min_longitude=80&max_longitude=70",
        "page_size=0",
    ]:
        assert client.get(f"/api/risk?{query}", headers=headers).status_code == 422, query


def test_get_risk_by_id_and_404(client, db_session):
    ds = make_dataset(db_session, DatasetKind.BIODIVERSITY)
    row = make_risk(db_session, make_biodiversity_observation(db_session, ds))
    headers = auth_headers(client)

    ok = client.get(f"/api/risk/{row.id}", headers=headers)
    assert ok.status_code == 200 and ok.json()["risk_level"] == "HIGH"
    assert client.get(f"/api/risk/{uuid.uuid4()}", headers=headers).status_code == 404
