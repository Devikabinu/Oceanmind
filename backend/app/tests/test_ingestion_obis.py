"""End-to-end test against the REAL OBIS REST API and a real local
Postgres+PostGIS database. Requires network access.
"""

import pytest


def _register_researcher(client, email="obis-researcher@example.com"):
    client.post(
        "/api/auth/register",
        json={
            "email": email,
            "full_name": "Researcher",
            "password": "s3cure-pass",
            "role": "RESEARCHER",
        },
    )
    login = client.post("/api/auth/login", json={"email": email, "password": "s3cure-pass"})
    return login.json()["access_token"]


@pytest.mark.network
def test_obis_ingestion_end_to_end(client):
    token = _register_researcher(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/ingestion/obis",
        headers=headers,
        json={
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "min_latitude": 10.0,
            "max_latitude": 15.0,
            "min_longitude": 70.0,
            "max_longitude": 75.0,
        },
    )
    assert response.status_code == 202
    job = response.json()
    dataset_id = job["dataset_id"]

    job_response = client.get(f"/api/ingestion/jobs/{job['id']}", headers=headers)
    completed_job = job_response.json()
    assert completed_job["status"] == "COMPLETED", completed_job.get("error_message")
    assert completed_job["records_read"] > 0
    assert completed_job["records_valid"] > 0
    assert completed_job["records_rejected"] > 0  # OBIS ON_LAND flags are expected here

    obs_response = client.get(
        "/api/biodiversity-observations",
        headers=headers,
        params={"dataset_id": dataset_id, "page_size": 500},
    )
    obs_body = obs_response.json()
    assert obs_body["total"] == completed_job["records_valid"]
    assert len(obs_body["items"]) > 0

    sample = obs_body["items"][0]
    assert 10.0 <= sample["latitude"] <= 15.0
    assert 70.0 <= sample["longitude"] <= 75.0
    assert isinstance(sample["scientific_name"], str) and len(sample["scientific_name"]) > 0

    quality_response = client.get(f"/api/data-quality/{dataset_id}", headers=headers)
    reports = quality_response.json()
    assert len(reports) == 1
    assert reports[0]["invalid_coordinates"] > 0
