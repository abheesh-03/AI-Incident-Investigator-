"""Run the agent over the labeled synthetic dataset and emit metrics.

Exits non-zero if exact-match accuracy is below the CI gate threshold
(defaults to 70%; override with EVAL_GATE_THRESHOLD).
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from app.agent.graph import build_graph
from app.core.embeddings import embed_text
from app.core.metrics import eval_accuracy
from app.db.models import EvalRun, IncidentPostmortem
from app.db.session import SessionLocal
from scripts.synth import generate_incidents, generate_postmortems

GATE_THRESHOLD = float(os.getenv("EVAL_GATE_THRESHOLD", "0.70"))
DATASET_PATH = Path(__file__).parent / "dataset" / "incidents.json"


def _ensure_postmortems(db) -> None:
    if db.query(IncidentPostmortem).count() > 0:
        return
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


def _judge_score(expected_root_cause: str, predicted_root_cause: str, category_match: bool) -> float:
    """Simple LLM-as-judge stand-in: rewards substring overlap + category match.

    Replace with a real LLM judge in production — kept deterministic here so
    CI runs are reproducible without an API key.
    """
    if not predicted_root_cause:
        return 0.0
    overlap = len(set(expected_root_cause.lower().split()) & set(predicted_root_cause.lower().split()))
    overlap_score = min(1.0, overlap / 5.0)
    return round(0.6 * (1.0 if category_match else 0.0) + 0.4 * overlap_score, 3) * 5  # 0..5


def run() -> int:
    if not DATASET_PATH.exists():
        print(f"Dataset missing at {DATASET_PATH}; run `python eval/build_dataset.py` first.")
        return 2

    dataset = json.loads(DATASET_PATH.read_text())
    incidents = {inc.external_id: inc for inc in generate_incidents(n=len(dataset))}

    db = SessionLocal()
    try:
        _ensure_postmortems(db)
        graph = build_graph(db)

        results: list[dict] = []
        correct = 0
        total_judge = 0.0
        total_duration = 0.0
        for entry in dataset:
            synthetic = incidents[entry["external_id"]]
            initial_state = {
                "incident_id": 0,
                "started_at": synthetic.started_at.isoformat(),
                "ended_at": synthetic.ended_at.isoformat(),
                "affected_services": synthetic.services,
                "logs": [
                    {
                        **log,
                        "timestamp": log["timestamp"].isoformat(),
                    }
                    for log in synthetic.logs
                ],
                "metrics": [
                    {**m, "timestamp": m["timestamp"].isoformat()} for m in synthetic.metrics
                ],
                "deployments": [
                    {**d, "timestamp": d["timestamp"].isoformat()} for d in synthetic.deployments
                ],
                "trace": [],
            }
            t0 = time.perf_counter()
            final = graph.invoke(initial_state)
            duration = time.perf_counter() - t0
            synthesis = final.get("synthesis", {})
            predicted_category = synthesis.get("root_cause_category", "")
            expected_category = entry["expected_root_cause_category"]
            match = predicted_category == expected_category
            if match:
                correct += 1
            judge = _judge_score(entry["expected_root_cause"], synthesis.get("root_cause", ""), match)
            total_judge += judge
            total_duration += duration
            results.append(
                {
                    "external_id": entry["external_id"],
                    "expected_category": expected_category,
                    "predicted_category": predicted_category,
                    "match": match,
                    "confidence": synthesis.get("confidence"),
                    "judge_score": judge,
                    "duration_seconds": round(duration, 3),
                }
            )

        n = len(results)
        accuracy = correct / n if n else 0.0
        mean_judge = total_judge / n if n else 0.0
        mean_duration = total_duration / n if n else 0.0
        eval_accuracy.set(accuracy)

        db.add(
            EvalRun(
                dataset_size=n,
                exact_match_accuracy=accuracy,
                judge_score=mean_judge,
                mean_duration_seconds=mean_duration,
                details=results,
            )
        )
        db.commit()

        report = {
            "dataset_size": n,
            "exact_match_accuracy": round(accuracy, 3),
            "judge_score": round(mean_judge, 3),
            "mean_duration_seconds": round(mean_duration, 3),
            "gate_threshold": GATE_THRESHOLD,
            "passed": accuracy >= GATE_THRESHOLD,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        report_path = Path(__file__).parent / "last_report.json"
        report_path.write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))

        return 0 if accuracy >= GATE_THRESHOLD else 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(run())
