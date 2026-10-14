def test_register_creates_user(client):
    response = client.post(
        "/api/auth/register",
        json={
            "email": "researcher@example.com",
            "full_name": "Ada Lovelace",
            "password": "s3cure-pass",
            "role": "RESEARCHER",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "researcher@example.com"
    assert body["role"] == "RESEARCHER"
    assert "password" not in body
    assert "hashed_password" not in body


def test_register_duplicate_email_rejected(client):
    payload = {
        "email": "dup@example.com",
        "full_name": "Dup User",
        "password": "s3cure-pass",
    }
    first = client.post("/api/auth/register", json=payload)
    assert first.status_code == 201

    second = client.post("/api/auth/register", json=payload)
    assert second.status_code == 409


def test_login_returns_token_for_valid_credentials(client):
    client.post(
        "/api/auth/register",
        json={
            "email": "login@example.com",
            "full_name": "Login User",
            "password": "correct-pass",
        },
    )

    response = client.post(
        "/api/auth/login",
        json={"email": "login@example.com", "password": "correct-pass"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


def test_login_rejects_wrong_password(client):
    client.post(
        "/api/auth/register",
        json={
            "email": "wrongpass@example.com",
            "full_name": "User",
            "password": "correct-pass",
        },
    )

    response = client.post(
        "/api/auth/login",
        json={"email": "wrongpass@example.com", "password": "incorrect-pass"},
    )
    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_current_user(client):
    client.post(
        "/api/auth/register",
        json={
            "email": "me@example.com",
            "full_name": "Me User",
            "password": "correct-pass",
        },
    )
    login_response = client.post(
        "/api/auth/login",
        json={"email": "me@example.com", "password": "correct-pass"},
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    assert response.json()["email"] == "me@example.com"


def test_logout_requires_valid_token(client):
    response = client.post("/api/auth/logout")
    assert response.status_code == 401
