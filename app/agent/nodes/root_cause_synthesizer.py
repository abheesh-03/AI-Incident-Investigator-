from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.agent.rag import find_similar_postmortems
from app.agent.state import InvestigationState
from app.core.llm import call_llm_tool, heuristic_category
from app.core.metrics import agent_node_duration_seconds

NODE = "root_cause_synthesizer"

VALID_CATEGORIES = [
    "db_pool_exhaustion",
    "memory_leak",
    "timeout_cascade",
    "misconfiguration",
    "dependency_failure",
]

# Each example is a (signal_summary, correct_category) pair the model sees in
# the prompt. They're not real incidents — they're canonical templates that
# anchor the model to the right vocabulary for each bucket.
FEW_SHOT_EXAMPLES = """
Worked examples (study the signal → category mapping):

Example 1
  Dominant log: "psycopg.OperationalError: too many connections for role 'app'"
  Top metric anomaly: db_connection_wait_ms spiking 400% above baseline
  Correct category: db_pool_exhaustion

Example 2
  Dominant log: "java.lang.OutOfMemoryError: Java heap space" / "OOMKilled"
  Top metric anomaly: process_resident_memory_bytes growing unbounded
  Correct category: memory_leak

Example 3
  Dominant log: "504 Gateway Timeout from inventory-svc" / "deadline exceeded calling inventory-svc"
  Top metric anomaly: http_request_duration_p95_ms spiking on internal calls
  Correct category: timeout_cascade

Example 4
  Dominant log: "config error: missing required env var" / "invalid feature flag"
  Top metric anomaly: config_reload_errors_total spike right after deploy
  Correct category: misconfiguration

Example 5
  Dominant log: "stripe.error.APIConnectionError" / "dns lookup failed" / "TLS handshake failed against api.stripe.com"
  Top metric anomaly: downstream_error_rate spiking
  Correct category: dependency_failure
"""

PROMPT = """You are producing the final root-cause hypothesis for a production incident.

Category definitions (mutually exclusive):
- db_pool_exhaustion: the DATABASE connection pool ran out of connections, or the application is waiting on DB connections. Signals: "connection pool", "too many connections", "pool_size", DB wait time spike.
- memory_leak: the PROCESS exhausted memory or was OOMKilled. Signals: "OutOfMemoryError", "OOMKilled", heap exhaustion, RSS growth.
- timeout_cascade: an UPSTREAM/INTERNAL service slowed down and timeouts cascaded. Signals: 504 from an internal service, "deadline exceeded calling X", request_duration_p95 spike on internal calls. NOT for third-party APIs.
- misconfiguration: a BAD CONFIG/ENV var was deployed. Signals: "config error", "missing env var", "invalid feature flag", malformed config.
- dependency_failure: a THIRD-PARTY/EXTERNAL provider failed (Stripe, DNS, TLS, external 503). Signals: "stripe.error", "dns lookup", "TLS handshake", downstream provider 5xx.

{few_shot}

Now classify this incident.

Log analysis: {log_analysis}
Metric analysis: {metric_analysis}
Deployments in window: {deployments}

Most similar past postmortems (retrieved via RAG):
{postmortems}

Keyword-classifier prior (cheap heuristic — useful but NOT authoritative):
  → suggests category: {heuristic_hint}

Call the submit_root_cause tool with your final structured answer.
"""

TOOL_SPEC = {
    "name": "submit_root_cause",
    "description": "Submit the final structured root cause hypothesis for the incident.",
    "input_schema": {
        "type": "object",
        "properties": {
            "root_cause": {
                "type": "string",
                "description": "Concise one-sentence root cause statement.",
            },
            "root_cause_category": {
                "type": "string",
                "enum": VALID_CATEGORIES,
                "description": "The single best-matching category.",
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "How confident you are in the category (0-1).",
            },
            "triggered_by": {
                "type": "string",
                "description": "What triggered the incident (e.g. deployment vX.Y.Z at HH:MM).",
            },
            "evidence": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
                "description": "Bullet-style evidence points supporting the conclusion.",
            },
            "suggested_fix": {
                "type": "string",
                "description": "Actionable remediation suggestion.",
            },
        },
        "required": [
            "root_cause",
            "root_cause_category",
            "confidence",
            "triggered_by",
            "evidence",
            "suggested_fix",
        ],
    },
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

        # Cheap keyword prior over the log + metric text — gives the model a
        # known-good signal even when its reasoning drifts.
        prior_text = " ".join(
            [
                log_analysis.get("dominant_pattern", ""),
                " ".join(p["message"] for p in log_analysis.get("top_patterns", [])[:5]),
                " ".join(metric_analysis.get("correlated_metrics", [])),
            ]
        )
        heuristic_hint, _ = heuristic_category(prior_text)

        prompt = PROMPT.format(
            few_shot=FEW_SHOT_EXAMPLES,
            log_analysis=log_analysis,
            metric_analysis=metric_analysis,
            deployments=deployments_text,
            postmortems=postmortems_text,
            heuristic_hint=heuristic_hint,
        )
        parsed = call_llm_tool(prompt, node=NODE, tool=TOOL_SPEC)

        # The tool's enum already constrains the category at the API level —
        # but if the heuristic fallback fired (no API key, transport error),
        # ensure the result is still in-enum.
        valid = set(VALID_CATEGORIES)
        rag_category = rag_hits[0]["root_cause_category"] if rag_hits else "misconfiguration"
        category = parsed.get("root_cause_category", "")
        if category not in valid:
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
                "heuristic_hint": heuristic_hint,
                "output": synthesis,
            }
        )

        return {**state, "rag_hits": rag_hits, "synthesis": synthesis, "trace": trace}

    return root_cause_synthesizer_node
