from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.agent.runner import run_investigation
from app.api.schemas import (
    InvestigateRequest,
    InvestigationOut,
    InvestigationSummary,
)
from app.core.auth import require_auth
from app.db.models import AuditLog, Incident, Investigation
from app.db.session import SessionLocal, get_db

router = APIRouter(tags=["investigate"])


def _background_run(investigation_id: int) -> None:
    db = SessionLocal()
    try:
        investigation = db.get(Investigation, investigation_id)
        if investigation is not None:
            run_investigation(db, investigation)
    finally:
        db.close()


@router.post("/investigate", response_model=InvestigationOut)
def trigger_investigation(
    request: InvestigateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> InvestigationOut:
    incident = db.execute(
        select(Incident).where(Incident.external_id == request.external_id)
    ).scalar_one_or_none()
    if incident is None:
        incident = Incident(
            external_id=request.external_id,
            title=request.title,
            started_at=request.started_at,
            ended_at=request.ended_at,
            affected_services=request.affected_services,
            status="investigating",
        )
        db.add(incident)
        db.flush()

    investigation = Investigation(incident_id=incident.id, status="pending")
    db.add(investigation)
    db.add(
        AuditLog(
            actor=principal.get("sub", "unknown"),
            action="trigger_investigation",
            resource=f"incident:{incident.external_id}",
            metadata_json={"investigation_id": None},
        )
    )
    db.commit()
    db.refresh(investigation)

    background_tasks.add_task(_background_run, investigation.id)
    return InvestigationOut.model_validate(investigation)


@router.get("/investigations/{investigation_id}", response_model=InvestigationOut)
def get_investigation(
    investigation_id: int,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> InvestigationOut:
    investigation = db.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return InvestigationOut.model_validate(investigation)


@router.get("/investigations", response_model=list[InvestigationSummary])
def list_investigations(
    limit: int = 50,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> list[InvestigationSummary]:
    rows = db.execute(
        select(Investigation).order_by(desc(Investigation.created_at)).limit(limit)
    ).scalars().all()
    return [InvestigationSummary.model_validate(r) for r in rows]
