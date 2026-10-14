import uuid

import pytest

from app.models.enums import AlertSeverity, AlertStatus
from app.tests._helpers import auth_headers, make_alert, utc


def _seed(db_session):
    make_alert(db_session, "SST_ANOMALY", AlertSeverity.HIGH, AlertStatus.NEW, utc(2026, 6, 1))
    make_alert(db_session, "ECOLOGICAL_RISK", AlertSeverity.CRITICAL, AlertStatus.ACKNOWLEDGED, utc(2026, 6, 10))
    make_alert(db_session, "SST_FORECAST_HEAT", AlertSeverity.LOW, AlertStatus.RESOLVED, utc(2026, 6, 20))


def test_alerts_require_auth(client, db_session):
    alert = make_alert(db_session)
    assert client.get("/api/alerts").status_code == 401
    assert client.get(f"/api/alerts/{alert.id}").status_code == 401
    assert client.patch(f"/api/alerts/{alert.id}", json={"status": "ACKNOWLEDGED"}).status_code == 401


def test_list_alerts_paginated(client, db_session):
    _seed(db_session)
    body = client.get("/api/alerts?page_size=2", headers=auth_headers(client)).json()
    assert body["total"] == 3 and len(body["items"]) == 2
    assert body["items"][0]["alert_type"] == "SST_FORECAST_HEAT"  # newest first
    assert {"severity", "status", "message", "related_forecast_id", "resolved_at"} <= body["items"][0].keys()


def test_list_alerts_filters(client, db_session):
    _seed(db_session)
    headers = auth_headers(client)

    assert client.get("/api/alerts?status=NEW", headers=headers).json()["total"] == 1
    assert client.get("/api/alerts?severity=CRITICAL", headers=headers).json()["total"] == 1
    assert client.get("/api/alerts?alert_type=SST_ANOMALY", headers=headers).json()["total"] == 1
    assert client.get("/api/alerts?alert_type=NOPE", headers=headers).json()["total"] == 0
    by_date = client.get(
        "/api/alerts?start_date=2026-06-05T00:00:00Z&end_date=2026-06-15T00:00:00Z", headers=headers
    ).json()
    assert by_date["total"] == 1
    combined = client.get("/api/alerts?status=RESOLVED&severity=LOW", headers=headers).json()
    assert combined["total"] == 1


def test_list_alerts_bad_filters_422(client):
    headers = auth_headers(client)
    for query in [
        "status=CLOSED",
        "severity=SEVERE",
        "alert_type=",
        "start_date=2026-06-10T00:00:00Z&end_date=2026-06-01T00:00:00Z",
        "page=0",
    ]:
        assert client.get(f"/api/alerts?{query}", headers=headers).status_code == 422, query


def test_get_alert_by_id_and_404(client, db_session):
    alert = make_alert(db_session)
    headers = auth_headers(client)
    ok = client.get(f"/api/alerts/{alert.id}", headers=headers)
    assert ok.status_code == 200 and ok.json()["status"] == "NEW"
    assert client.get(f"/api/alerts/{uuid.uuid4()}", headers=headers).status_code == 404


@pytest.mark.parametrize("role", ["ADMIN", "RESEARCHER"])
def test_patch_alert_acknowledge_then_resolve(client, db_session, role):
    alert = make_alert(db_session)
    headers = auth_headers(client, role)

    ack = client.patch(f"/api/alerts/{alert.id}", headers=headers, json={"status": "ACKNOWLEDGED"})
    assert ack.status_code == 200
    assert ack.json()["status"] == "ACKNOWLEDGED" and ack.json()["resolved_at"] is None

    resolved = client.patch(f"/api/alerts/{alert.id}", headers=headers, json={"status": "RESOLVED"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED" and resolved.json()["resolved_at"] is not None

    # persisted
    assert client.get(f"/api/alerts/{alert.id}", headers=headers).json()["status"] == "RESOLVED"


def test_patch_alert_forbidden_for_plain_user(client, db_session):
    alert = make_alert(db_session)
    response = client.patch(
        f"/api/alerts/{alert.id}", headers=auth_headers(client, "USER"), json={"status": "ACKNOWLEDGED"}
    )
    assert response.status_code == 403
    db_session.expire_all()
    assert db_session.get(type(alert), alert.id).status == AlertStatus.NEW


def test_patch_alert_rejects_backward_and_repeat_transitions(client, db_session):
    headers = auth_headers(client, "RESEARCHER")
    resolved = make_alert(db_session, status=AlertStatus.RESOLVED)
    acked = make_alert(db_session, status=AlertStatus.ACKNOWLEDGED)

    assert client.patch(f"/api/alerts/{resolved.id}", headers=headers, json={"status": "NEW"}).status_code == 409
    assert client.patch(f"/api/alerts/{resolved.id}", headers=headers, json={"status": "RESOLVED"}).status_code == 409
    assert client.patch(f"/api/alerts/{acked.id}", headers=headers, json={"status": "NEW"}).status_code == 409
    assert client.patch(f"/api/alerts/{acked.id}", headers=headers, json={"status": "ACKNOWLEDGED"}).status_code == 409


def test_patch_alert_bad_body_and_404(client, db_session):
    headers = auth_headers(client, "ADMIN")
    alert = make_alert(db_session)
    assert client.patch(f"/api/alerts/{alert.id}", headers=headers, json={"status": "DONE"}).status_code == 422
    assert client.patch(f"/api/alerts/{alert.id}", headers=headers, json={}).status_code == 422
    assert (
        client.patch(f"/api/alerts/{uuid.uuid4()}", headers=headers, json={"status": "ACKNOWLEDGED"}).status_code
        == 404
    )


def test_patch_alert_ignores_other_fields(client, db_session):
    headers = auth_headers(client, "ADMIN")
    alert = make_alert(db_session)
    response = client.patch(
        f"/api/alerts/{alert.id}",
        headers=headers,
        json={"status": "ACKNOWLEDGED", "severity": "LOW", "message": "hacked"},
    )
    assert response.status_code == 200
    assert response.json()["severity"] == "HIGH" and response.json()["message"] == "test alert"
