"""End-to-end test of the spatiotemporal alignment feature: ingest real NOAA
SST and real OBIS biodiversity data for the same region/period, then verify
match_biodiversity_to_environment (POST /api/alignment/run) finds nearest
neighbors that actually satisfy the requested radius and time window.
"""

import pytest


def _register_researcher(client, email="alignment-researcher@example.com"):
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
def test_alignment_matches_satisfy_radius_and_window(client):
    token = _register_researcher(client)
    headers = {"Authorization": f"Bearer {token}"}

    # This region/window was chosen empirically (see dev notes) because it has
    # a real, non-ON_LAND-flagged OBIS occurrence density high enough to
    # reliably produce at least one genuine spatiotemporal match, unlike the
    # coastal-bird-dominated bbox used in the other ingestion tests.
    bbox = {
        "min_latitude": 0.0,
        "max_latitude": 5.0,
        "min_longitude": 105.0,
        "max_longitude": 110.0,
    }

    noaa_job = client.post(
        "/api/ingestion/noaa",
        headers=headers,
        json={"start_date": "2023-06-01", "end_date": "2023-07-31", **bbox},
    ).json()
    obis_job = client.post(
        "/api/ingestion/obis",
        headers=headers,
        json={"start_date": "2023-06-01", "end_date": "2023-07-31", **bbox},
    ).json()

    for job in (noaa_job, obis_job):
        status_response = client.get(f"/api/ingestion/jobs/{job['id']}", headers=headers).json()
        assert status_response["status"] == "COMPLETED", status_response.get("error_message")

    run_response = client.post(
        "/api/alignment/run",
        headers=headers,
        json={
            "spatial_radius_km": 25.0,
            "temporal_window_hours": 24.0,
            "biodiversity_dataset_id": obis_job["dataset_id"],
        },
    )
    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["matches_created"] > 0

    results = client.get(
        "/api/alignment/results", headers=headers, params={"page_size": 500}
    ).json()
    assert results["total"] == run_body["matches_created"]

    for match in results["items"]:
        assert match["distance_km"] <= 25.0
        assert match["time_difference_hours"] <= 24.0
        assert match["spatial_radius_km"] == 25.0
        assert match["temporal_window_hours"] == 24.0
