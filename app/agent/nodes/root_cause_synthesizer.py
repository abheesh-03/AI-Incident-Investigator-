from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.agent.rag import find_similar_postmortems
from app.agent.state import InvestigationState
from app.core.llm import call_llm, extract_json
from app.core.metrics import agent_node_duration_seconds

NODE = "root_cause_synthesizer"

PROMPT = """You are producing the final root-cause hypothesis for an incident.

Log analysis: {log_analysis}
Metric analysis: {metric_analysis}
Deployments in window: {deployments}

Most similar past postmortems (retrieved via RAG):
{postmortems}

Reply with strict JSON only:
{{
  "root_cause": "concise 1-sentence root cause",
  "root_cause_category": "one of: db_pool_exhaustion, memory_leak, timeout_cascade, misconfiguration, dependency_failure",
  "confidence": 0.0,
  "triggered_by": "what triggered it (e.g. deployment vX.Y.Z at HH:MM)",
  "evidence": ["bullet 1", "bullet 2", "bullet 3"],
  "suggested_fix": "actionable remediation"
}}
"""

VALID_CATEGORIES = {
    "db_pool_exhaustion",
    "memory_leak",
    "timeout_cascade",
    "misconfiguration",
    "dependency_failure",
}


def make_synthesizer_node(db: Session):
    def root_cause_synthesizer_node(state: InvestigationState) -> InvestigationState:
        start = time.perf_counter()
        log_analysis = state.get("log_analysis", {})
        metric_analysis = state.get("metric_analysis", {})
        deployments = state.get("deployments", [])

        query_for_rag = " ".join(
            [
                log_analysis.get("dominant_pattern", ""),
                metric_analysis.get("refined_hypothesis", ""),
                " ".join(metric_analysis.get("correlated_metrics", [])),
            ]
        ).strip() or "incident investigation"

        rag_hits = find_similar_postmortems(db, query_for_rag, limit=3)

        postmortems_text = "\n".join(
            f"- {p['external_id']} [{p['root_cause_category']}]: {p['summary']}"
            for p in rag_hits
        ) or "- (no similar past postmortems found)"

        deployments_text = "\n".join(
            f"- {d.get('timestamp')} | {d.get('service')} | {d.get('version')}"
            for d in deployments
        ) or "- (no deployments)"

        prompt = PROMPT.format(
            log_analysis=log_analysis,
            metric_analysis=metric_analysis,
            deployments=deployments_text,
            postmortems=postmortems_text,
        )
        raw = call_llm(prompt, node=NODE)
        parsed = extract_json(raw) or {}

        # When the LLM fails to return parseable JSON or nominates a category
        # outside the allowed enum, bias toward the closest RAG postmortem —
        # the embedding space is the most reliable category signal we have.
        rag_category = rag_hits[0]["root_cause_category"] if rag_hits else "misconfiguration"
        category = parsed.get("root_cause_category", "")
        if category not in VALID_CATEGORIES:
            category = rag_category

        confidence = float(parsed.get("confidence", metric_analysis.get("confidence_hint", 0.6)))
        confidence = max(0.0, min(1.0, confidence))

        synthesis = {
            "root_cause": parsed.get("root_cause", log_analysis.get("root_cause_hypothesis", "")),
            "root_cause_category": category,
            "confidence": confidence,
            "triggered_by": parsed.get(
                "triggered_by", metric_analysis.get("deployment_link", "unknown")
            ),
            "evidence": parsed.get("evidence", []) or [
                log_analysis.get("dominant_pattern", ""),
                *(a["metric"] for a in metric_analysis.get("anomalies", [])[:2]),
            ],
            "suggested_fix": parsed.get(
                "suggested_fix", "Investigate the linked deployment and roll back if necessary."
            ),
            "similar_past_incidents": [p["external_id"] for p in rag_hits],
        }

        elapsed = time.perf_counter() - start
        agent_node_duration_seconds.labels(node=NODE).observe(elapsed)
        trace = list(state.get("trace") or [])
        trace.append(
            {
                "node": NODE,
                "duration_s": round(elapsed, 3),
                "rag_hits": [p["external_id"] for p in rag_hits],
                "output": synthesis,
            }
        )

        return {**state, "rag_hits": rag_hits, "synthesis": synthesis, "trace": trace}

    return root_cause_synthesizer_node
