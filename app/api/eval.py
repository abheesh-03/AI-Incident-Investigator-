from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.auth import require_auth
from app.db.models import EvalRun
from app.db.session import get_db

router = APIRouter(prefix="/eval", tags=["eval"])


@router.get("/report")
def latest_eval_report(
    db: Session = Depends(get_db),
    principal: dict = Depends(require_auth),
) -> dict:
    row = db.execute(select(EvalRun).order_by(desc(EvalRun.created_at)).limit(1)).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no evaluation has been run yet")
    return {
        "id": row.id,
        "dataset_size": row.dataset_size,
        "exact_match_accuracy": row.exact_match_accuracy,
        "judge_score": row.judge_score,
        "mean_duration_seconds": row.mean_duration_seconds,
        "created_at": row.created_at.isoformat(),
        "details_sample": row.details[:5] if row.details else [],
    }
