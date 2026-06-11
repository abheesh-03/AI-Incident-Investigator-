def test_health(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_endpoint(client) -> None:
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "investigations_total" in response.text


def test_auth_required(client) -> None:
    response = client.get("/investigations")
    assert response.status_code == 401
