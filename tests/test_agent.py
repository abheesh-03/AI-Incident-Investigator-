from __future__ import annotations

from datetime import datetime, timezone

from app.agent.graph import build_graph
from app.core.embeddings import embed_text
from app.db.models import IncidentPostmortem
from app.db.session import SessionLocal
from scripts.synth import generate_incidents, generate_postmortems


def _seed_postmortems(db) -> None:
    if db.query(IncidentPostmortem).count() > 0:
        return
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


def test_graph_runs_end_to_end() -> None:
    db = SessionLocal()
    try:
        _seed_postmortems(db)
        graph = build_graph(db)
        incident = generate_incidents(n=1)[0]
        state = {
            "incident_id": 0,
            "started_at": incident.started_at.isoformat(),
            "ended_at": incident.ended_at.isoformat(),
            "affected_services": incident.services,
            "logs": [{**log, "timestamp": log["timestamp"].isoformat()} for log in incident.logs],
            "metrics": [{**m, "timestamp": m["timestamp"].isoformat()} for m in incident.metrics],
            "deployments": [{**d, "timestamp": d["timestamp"].isoformat()} for d in incident.deployments],
            "trace": [],
        }
        result = graph.invoke(state)
        synthesis = result["synthesis"]
        assert synthesis["root_cause_category"] in {
            "db_pool_exhaustion",
            "memory_leak",
            "timeout_cascade",
            "misconfiguration",
            "dependency_failure",
        }
        assert 0.0 <= synthesis["confidence"] <= 1.0
        assert len(result["trace"]) == 3
        assert result["trace"][0]["node"] == "log_analyzer"
        assert result["trace"][-1]["node"] == "root_cause_synthesizer"
    finally:
        db.close()


def test_heuristic_llm_categorizes_db_pool() -> None:
    # Exercises the deterministic fallback directly so it stays meaningful
    # even when ANTHROPIC_API_KEY is set (real Claude wouldn't categorize a
    # bare keyword string into our enum without the full agent prompt).
    from app.core.llm import _heuristic_response, extract_json

    prompt = "Many logs say: DB connection pool exhausted, too many connections, pool_size"
    raw = _heuristic_response(prompt)
    parsed = extract_json(raw)
    assert parsed.get("root_cause_category") == "db_pool_exhaustion"
