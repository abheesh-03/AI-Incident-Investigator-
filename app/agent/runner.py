"""Top-level driver that pulls inputs from the DB, runs the LangGraph agent,
and persists the final investigation."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.graph import build_graph
from app.agent.state import InvestigationState
from app.core.metrics import (
    investigation_duration_seconds,
    investigations_total,
    root_cause_confidence,
)
from app.db.models import Deployment, Incident, Investigation, LogEntry, MetricPoint


def _gather_inputs(db: Session, incident: Incident) -> InvestigationState:
    started_at = incident.started_at
    ended_at = incident.ended_at or datetime.now(timezone.utc)
    services = incident.affected_services or []

    log_q = select(LogEntry).where(
        LogEntry.timestamp >= started_at,
        LogEntry.timestamp <= ended_at,
    )
    if services:
        log_q = log_q.where(LogEntry.service.in_(services))
    logs = [
        {
            "service": log.service,
            "level": log.level,
            "message": log.message,
            "timestamp": log.timestamp.isoformat(),
            "attributes": log.attributes or {},
        }
        for log in db.execute(log_q).scalars().all()
    ]

    metric_q = select(MetricPoint).where(
        MetricPoint.timestamp >= started_at,
        MetricPoint.timestamp <= ended_at,
    )
    if services:
        metric_q = metric_q.where(MetricPoint.service.in_(services))
    metrics = [
        {
            "service": m.service,
            "name": m.name,
            "value": m.value,
            "timestamp": m.timestamp.isoformat(),
            "labels": m.labels or {},
        }
        for m in db.execute(metric_q).scalars().all()
    ]

    # Pull deployments slightly before the incident — a deploy 30 min prior is
    # often the cause.
    from datetime import timedelta

    deploy_q = select(Deployment).where(
        Deployment.timestamp >= started_at - timedelta(hours=2),
        Deployment.timestamp <= ended_at,
    )
    if services:
        deploy_q = deploy_q.where(Deployment.service.in_(services))
    deployments = [
        {
            "service": d.service,
            "version": d.version,
            "deployer": d.deployer,
            "description": d.description,
            "timestamp": d.timestamp.isoformat(),
        }
        for d in db.execute(deploy_q).scalars().all()
    ]

    return {
        "incident_id": incident.id,
        "started_at": started_at.isoformat(),
        "ended_at": ended_at.isoformat(),
        "affected_services": services,
        "logs": logs,
        "metrics": metrics,
        "deployments": deployments,
        "trace": [],
    }


def run_investigation(db: Session, investigation: Investigation) -> Investigation:
    incident = db.get(Incident, investigation.incident_id)
    if incident is None:
        investigation.status = "failed"
        investigation.error = "incident_not_found"
        db.commit()
        return investigation

    investigation.status = "running"
    db.commit()
    started_wall = time.perf_counter()
    try:
        graph = build_graph(db)
        initial_state = _gather_inputs(db, incident)
        final_state = graph.invoke(initial_state)
        synthesis = final_state.get("synthesis", {})
        trace = final_state.get("trace", [])

        investigation.status = "completed"
        investigation.root_cause = synthesis.get("root_cause")
        investigation.root_cause_category = synthesis.get("root_cause_category")
        investigation.confidence = synthesis.get("confidence")
        investigation.triggered_by = synthesis.get("triggered_by")
        investigation.suggested_fix = synthesis.get("suggested_fix")
        investigation.evidence = synthesis.get("evidence") or []
        investigation.similar_past_incidents = synthesis.get("similar_past_incidents") or []
        investigation.agent_trace = trace
        investigation.duration_seconds = round(time.perf_counter() - started_wall, 3)
        investigation.completed_at = datetime.now(timezone.utc)

        investigations_total.labels(status="completed").inc()
        if investigation.confidence is not None:
            root_cause_confidence.observe(investigation.confidence)
        investigation_duration_seconds.observe(investigation.duration_seconds)
    except Exception as exc:  # pragma: no cover - defensive
        investigation.status = "failed"
        investigation.error = repr(exc)
        investigation.duration_seconds = round(time.perf_counter() - started_wall, 3)
        investigation.completed_at = datetime.now(timezone.utc)
        investigations_total.labels(status="failed").inc()

    db.commit()
    db.refresh(investigation)
    return investigation
