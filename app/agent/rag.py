from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.embeddings import embed_text
from app.db.models import IncidentPostmortem


def find_similar_postmortems(
    db: Session, query: str, limit: int = 3
) -> list[dict]:
    query_vec = embed_text(query)
    stmt = (
        select(IncidentPostmortem)
        .order_by(IncidentPostmortem.embedding.cosine_distance(query_vec))
        .limit(limit)
    )
    results = db.execute(stmt).scalars().all()
    return [
        {
            "external_id": pm.external_id,
            "title": pm.title,
            "summary": pm.summary,
            "root_cause": pm.root_cause,
            "root_cause_category": pm.root_cause_category,
            "resolution": pm.resolution,
            "occurred_at": pm.occurred_at.isoformat(),
        }
        for pm in results
    ]
