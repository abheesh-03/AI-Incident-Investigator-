from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.schemas import DeploymentIn, IngestResponse, LogIn, MetricIn
from app.core.auth import require_auth
from app.core.metrics import ingestion_records_total
from app.db.models import AuditLog, Deployment, LogEntry, MetricPoint
from app.db.session import get_db

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _audit(db: Session, actor: str, action: str, count: int) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            resource=f"count={count}",
            metadata_json={"count": count},
        )
    )


@router.post("/logs", response_model=IngestResponse)
def ingest_logs(
    payload: list[LogIn],
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> IngestResponse:
    rows = [
        LogEntry(
            service=item.service,
            level=item.level,
            message=item.message,
            timestamp=item.timestamp,
            attributes=item.attributes,
        )
        for item in payload
    ]
    db.add_all(rows)
    ingestion_records_total.labels(kind="logs").inc(len(rows))
    _audit(db, principal.get("sub", "unknown"), "ingest_logs", len(rows))
    db.commit()
    return IngestResponse(ingested=len(rows))


@router.post("/metrics", response_model=IngestResponse)
def ingest_metrics(
    payload: list[MetricIn],
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> IngestResponse:
    rows = [
        MetricPoint(
            service=item.service,
            name=item.name,
            value=item.value,
            timestamp=item.timestamp,
            labels=item.labels,
        )
        for item in payload
    ]
    db.add_all(rows)
    ingestion_records_total.labels(kind="metrics").inc(len(rows))
    _audit(db, principal.get("sub", "unknown"), "ingest_metrics", len(rows))
    db.commit()
    return IngestResponse(ingested=len(rows))


@router.post("/deployments", response_model=IngestResponse)
def ingest_deployments(
    payload: list[DeploymentIn],
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> IngestResponse:
    rows = [
        Deployment(
            service=item.service,
            version=item.version,
            deployer=item.deployer,
            description=item.description,
            timestamp=item.timestamp,
        )
        for item in payload
    ]
    db.add_all(rows)
    ingestion_records_total.labels(kind="deployments").inc(len(rows))
    _audit(db, principal.get("sub", "unknown"), "ingest_deployments", len(rows))
    db.commit()
    return IngestResponse(ingested=len(rows))
