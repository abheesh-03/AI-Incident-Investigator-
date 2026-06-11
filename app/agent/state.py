from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    incident_id: int
    started_at: datetime
    ended_at: datetime | None
    affected_services: list[str]

    # Raw inputs gathered before the graph runs
    logs: list[dict[str, Any]]
    metrics: list[dict[str, Any]]
    deployments: list[dict[str, Any]]

    # Node outputs
    log_analysis: dict[str, Any]
    metric_analysis: dict[str, Any]
    rag_hits: list[dict[str, Any]]
    synthesis: dict[str, Any]

    # Audit trail of every node execution
    trace: list[dict[str, Any]]
