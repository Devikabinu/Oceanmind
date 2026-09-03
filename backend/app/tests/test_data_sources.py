def _register_and_login(client, email="user@example.com"):
    client.post(
        "/api/auth/register",
        json={"email": email, "full_name": "Test User", "password": "s3cure-pass"},
    )
    login = client.post("/api/auth/login", json={"email": email, "password": "s3cure-pass"})
    return login.json()["access_token"]


def test_list_data_sources_requires_auth(client):
    response = client.get("/api/data-sources")
    assert response.status_code == 401


def test_list_data_sources_is_prepopulated(client):
    token = _register_and_login(client)
    response = client.get(
        "/api/data-sources", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    names = {source["name"] for source in response.json()}
    assert names == {"NOAA OISST v2.1", "Copernicus Marine SST", "OBIS"}


def test_list_datasets_paginated_shape(client):
    token = _register_and_login(client, email="datasets@example.com")
    response = client.get(
        "/api/datasets", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {"items": [], "total": 0, "page": 1, "page_size": 20}
