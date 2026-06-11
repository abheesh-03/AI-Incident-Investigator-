"""Thin LLM client wrapper.

If ANTHROPIC_API_KEY is set, calls Claude via the official SDK. Otherwise
falls back to a deterministic heuristic JSON response so the agent works
offline (CI, demos, and reviewers without an API key).
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.core.config import get_settings
from app.core.metrics import agent_llm_calls_total

settings = get_settings()


_CATEGORY_KEYWORDS = {
    "db_pool_exhaustion": [
        "connection pool", "pool exhaust", "db wait", "connections", "pool_size",
        "too many connections",
    ],
    "memory_leak": ["oom", "out of memory", "heap", "memory leak", "rss"],
    "timeout_cascade": ["timeout", "deadline exceeded", "upstream", "503", "504"],
    "misconfiguration": ["config", "env var", "missing", "invalid", "feature flag"],
    "dependency_failure": [
        "downstream", "third-party", "dns", "tls", "certificate", "stripe", "kafka",
    ],
}


def _heuristic_response(prompt: str) -> str:
    text = prompt.lower()
    scores = {cat: sum(1 for kw in kws if kw in text) for cat, kws in _CATEGORY_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        best = "misconfiguration"
    confidence = round(min(0.95, 0.55 + 0.08 * scores[best]), 2)
    return json.dumps(
        {
            "root_cause_category": best,
            "root_cause": f"Likely {best.replace('_', ' ')} based on observed signals.",
            "confidence": confidence,
            "triggered_by": "Recent deployment correlated with anomaly onset.",
            "evidence": [
                "Error rate increased sharply within the incident window.",
                "Latency p95 deviates from baseline.",
            ],
            "suggested_fix": "Roll back the suspected deployment or apply targeted mitigation.",
        }
    )


def call_llm(prompt: str, *, node: str, system: str | None = None) -> str:
    agent_llm_calls_total.labels(node=node, model=settings.llm_model).inc()
    if not settings.anthropic_api_key:
        return _heuristic_response(prompt)
    try:
        # Imported lazily so the heuristic path works without the SDK installed.
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key)
        msg = client.messages.create(
            model=settings.llm_model,
            max_tokens=1024,
            system=system or "You are an expert SRE incident investigator. Always reply with valid JSON.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
    except Exception:
        return _heuristic_response(prompt)


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort JSON extraction from an LLM response."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass
    return {}
