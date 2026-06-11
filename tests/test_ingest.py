from __future__ import annotations

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_ingest_logs(client, auth_headers) -> None:
    payload = [
        {
            "service": "payment-api",
            "level": "ERROR",
            "message": "DB connection pool exhausted",
            "timestamp": _now_iso(),
        }
    ]
    r = client.post("/ingest/logs", json=payload, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 1


def test_ingest_metrics(client, auth_headers) -> None:
    payload = [
        {
            "service": "payment-api",
            "name": "db_connection_wait_ms",
            "value": 420.5,
            "timestamp": _now_iso(),
        }
    ]
    r = client.post("/ingest/metrics", json=payload, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ingested"] == 1


def test_ingest_deployments(client, auth_headers) -> None:
    payload = [
        {
            "service": "payment-api",
            "version": "v2.3.1",
            "deployer": "alice",
            "timestamp": _now_iso(),
        }
    ]
    r = client.post("/ingest/deployments", json=payload, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ingested"] == 1
