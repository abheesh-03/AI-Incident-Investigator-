from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.agent.rag import find_similar_postmortems
from app.agent.state import InvestigationState
from app.core.llm import call_llm, extract_json
from app.core.metrics import agent_node_duration_seconds

NODE = "root_cause_synthesizer"

PROMPT = """You are producing the final root-cause hypothesis for a production incident.

Pick the single best matching root_cause_category from this fixed list. Use the
definitions strictly — they are mutually exclusive:

- db_pool_exhaustion: the DATABASE connection pool ran out of connections, or
  the application is waiting on DB connections. Signals: "connection pool",
  "too many connections", "pool_size", DB wait time spike.
- memory_leak: the PROCESS exhausted memory or was OOMKilled. Signals:
  "OutOfMemoryError", "OOMKilled", heap exhaustion, RSS growth.
- timeout_cascade: an UPSTREAM/INTERNAL service slowed down and timeouts
  cascaded. Signals: 504 from an internal service, "deadline exceeded calling
  X", request_duration_p95 spike on internal calls. NOT for third-party APIs.
- misconfiguration: a BAD CONFIG/ENV var was deployed. Signals: "config
  error", "missing env var", "invalid feature flag", malformed config.
- dependency_failure: a THIRD-PARTY/EXTERNAL provider failed (Stripe, DNS,
  TLS, external 503). Signals: "stripe.error", "dns lookup", "TLS handshake",
  downstream provider 5xx.

Log analysis: {log_analysis}
Metric analysis: {metric_analysis}
Deployments in window: {deployments}

Most similar past postmortems (retrieved via RAG):
{postmortems}

Reply with STRICT JSON only — no prose, no markdown fences:
{{
  "root_cause": "concise 1-sentence root cause",
  "root_cause_category": "<exact string from the list above>",
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
