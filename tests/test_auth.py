def test_token_round_trip(client, auth_headers) -> None:
    response = client.post("/auth/token", json={"api_key": "demo-key"})
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert token


def test_token_rejects_empty(client) -> None:
    response = client.post("/auth/token", json={"api_key": ""})
    assert response.status_code == 400


def test_bearer_accepted(client, auth_headers) -> None:
    response = client.get("/investigations", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
