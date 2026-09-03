"""End-to-end test against the REAL NOAA OISST OPeNDAP service and a real
local Postgres+PostGIS database. No mocks - this proves the full
fetch -> validate -> transform -> load pipeline actually works against live
data, not just that the code compiles. Requires network access.
"""

import pytest


def _register_researcher(client, email="noaa-researcher@example.com"):
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
def test_noaa_ingestion_end_to_end(client):
    token = _register_researcher(client)
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/ingestion/noaa",
        headers=headers,
        json={
            "start_date": "2023-06-10",
            "end_date": "2023-06-10",
            "min_latitude": 10.0,
            "max_latitude": 12.0,
            "min_longitude": 70.0,
            "max_longitude": 72.0,
        },
    )
    assert response.status_code == 202
    job = response.json()
    job_id = job["id"]
    dataset_id = job["dataset_id"]
    assert dataset_id is not None

    # TestClient executes FastAPI BackgroundTasks synchronously before the
    # outer request completes, so the job should already be COMPLETED here.
    job_response = client.get(f"/api/ingestion/jobs/{job_id}", headers=headers)
    assert job_response.status_code == 200
    completed_job = job_response.json()
    assert completed_job["status"] == "COMPLETED", completed_job.get("error_message")
    assert completed_job["records_read"] > 0
    assert completed_job["records_valid"] > 0
    assert completed_job["records_valid"] <= completed_job["records_read"]

    obs_response = client.get(
        "/api/ocean-observations",
        headers=headers,
        params={"dataset_id": dataset_id, "page_size": 500},
    )
    assert obs_response.status_code == 200
    obs_body = obs_response.json()
    assert obs_body["total"] == completed_job["records_valid"]
    assert len(obs_body["items"]) > 0

    sample = obs_body["items"][0]
    assert 10.0 <= sample["latitude"] <= 12.0
    assert 70.0 <= sample["longitude"] <= 72.0
    # Real Arabian Sea June SST is comfortably within this physical range.
    assert 20.0 <= sample["sst"] <= 35.0

    quality_response = client.get(f"/api/data-quality/{dataset_id}", headers=headers)
    assert quality_response.status_code == 200
    reports = quality_response.json()
    assert len(reports) == 1
    report = reports[0]
    assert report["records_read"] == completed_job["records_read"]
    assert report["records_valid"] == completed_job["records_valid"]
