"""Seed the database with synthetic incidents and historical postmortems.

Usage:
    python scripts/seed_incidents.py
"""
from __future__ import annotations

from app.core.embeddings import embed_text
from app.db.models import (
    Deployment,
    Incident,
    IncidentPostmortem,
    LogEntry,
    MetricPoint,
)
from app.db.session import SessionLocal
from scripts.synth import generate_incidents, generate_postmortems


def seed() -> None:
    db = SessionLocal()
    try:
        existing = db.query(IncidentPostmortem).count()
        if existing == 0:
            print("Seeding historical postmortems...")
            for pm in generate_postmortems():
                emb = embed_text(f"{pm['title']} {pm['root_cause']} {pm['resolution']}")
                db.add(
                    IncidentPostmortem(
                        external_id=pm["external_id"],
                        title=pm["title"],
                        summary=pm["summary"],
                        root_cause=pm["root_cause"],
                        root_cause_category=pm["root_cause_category"],
                        resolution=pm["resolution"],
                        occurred_at=pm["occurred_at"],
                        embedding=emb,
                    )
                )
            db.commit()

        existing_incidents = db.query(Incident).count()
        if existing_incidents > 0:
            print(f"Database already contains {existing_incidents} incidents; skipping incident seed.")
            return

        print("Seeding synthetic incidents, logs, metrics, deployments...")
        for incident in generate_incidents(n=50):
            row = Incident(
                external_id=incident.external_id,
                title=incident.title,
                started_at=incident.started_at,
                ended_at=incident.ended_at,
                affected_services=incident.services,
                status="closed",
            )
            db.add(row)
            db.flush()

            db.add_all(
                LogEntry(
                    service=log["service"],
                    level=log["level"],
                    message=log["message"],
                    timestamp=log["timestamp"],
                    attributes=log["attributes"],
                )
                for log in incident.logs
            )
            db.add_all(
                MetricPoint(
                    service=m["service"],
                    name=m["name"],
                    value=m["value"],
                    timestamp=m["timestamp"],
                    labels=m["labels"],
                )
                for m in incident.metrics
            )
            db.add_all(
                Deployment(
                    service=d["service"],
                    version=d["version"],
                    deployer=d["deployer"],
                    description=d["description"],
                    timestamp=d["timestamp"],
                )
                for d in incident.deployments
            )
        db.commit()
        print("Done.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
