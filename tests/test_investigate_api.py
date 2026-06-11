from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.embeddings import embed_text
from app.db.models import IncidentPostmortem
from app.db.session import SessionLocal
from scripts.synth import generate_incidents, generate_postmortems


def _seed(db) -> None:
    if db.query(IncidentPostmortem).count() == 0:
        for pm in generate_postmortems():
            db.add(
                IncidentPostmortem(
                    external_id=pm["external_id"],
                    title=pm["title"],
                    summary=pm["summary"],
                    root_cause=pm["root_cause"],
                    root_cause_category=pm["root_cause_category"],
                    resolution=pm["resolution"],
                    occurred_at=pm["occurred_at"],
                    embedding=embed_text(pm["root_cause"]),
                )
            )
        db.commit()


def test_full_investigation_flow(client, auth_headers) -> None:
    db = SessionLocal()
    try:
        _seed(db)
    finally:
        db.close()

    incident = generate_incidents(n=1)[0]
    # Ingest the synthetic signals the investigator will read back
    client.post(
        "/ingest/logs",
        headers=auth_headers,
        json=[
            {
                "service": log["service"],
                "level": log["level"],
                "message": log["message"],
                "timestamp": log["timestamp"].isoformat(),
                "attributes": log["attributes"],
            }
            for log in incident.logs
        ],
    )
    client.post(
        "/ingest/metrics",
        headers=auth_headers,
        json=[
            {
                "service": m["service"],
                "name": m["name"],
                "value": m["value"],
                "timestamp": m["timestamp"].isoformat(),
                "labels": m["labels"],
            }
            for m in incident.metrics
        ],
    )
    client.post(
        "/ingest/deployments",
        headers=auth_headers,
        json=[
            {
                "service": d["service"],
                "version": d["version"],
                "deployer": d["deployer"],
                "description": d["description"],
                "timestamp": d["timestamp"].isoformat(),
            }
            for d in incident.deployments
        ],
    )

    response = client.post(
        "/investigate",
        headers=auth_headers,
        json={
            "external_id": "INC-API-TEST-0001",
            "title": incident.title,
            "started_at": incident.started_at.isoformat(),
            "ended_at": incident.ended_at.isoformat(),
            "affected_services": incident.services,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    investigation_id = body["id"]

    # Background task runs in-thread under TestClient — fetch the final state.
    final = client.get(f"/investigations/{investigation_id}", headers=auth_headers).json()
    assert final["status"] == "completed"
    assert final["root_cause_category"] in {
        "db_pool_exhaustion",
        "memory_leak",
        "timeout_cascade",
        "misconfiguration",
        "dependency_failure",
    }
    assert 0.0 <= final["confidence"] <= 1.0
    assert len(final["agent_trace"]) == 3
