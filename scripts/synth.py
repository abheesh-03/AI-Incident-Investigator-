"""Generates synthetic incident data: logs, metrics, deployments, and labeled
postmortems across five canonical incident categories."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

CATEGORIES = [
    "db_pool_exhaustion",
    "memory_leak",
    "timeout_cascade",
    "misconfiguration",
    "dependency_failure",
]

CATEGORY_BLUEPRINTS = {
    "db_pool_exhaustion": {
        "title": "DB connection pool exhaustion",
        "services": ["payment-api", "transaction-worker"],
        "error_messages": [
            "psycopg.OperationalError: too many connections for role 'app'",
            "DB connection pool exhausted: 0 available of pool_size=10",
            "timeout waiting for available connection after 5000ms",
        ],
        "metric": "db_connection_wait_ms",
        "spike_factor": 4.0,
        "root_cause": "Database connection pool exhaustion under load",
        "fix": "Increase pool_size from 10 to 50 or roll back the recent deployment",
    },
    "memory_leak": {
        "title": "Service OOM from memory leak",
        "services": ["analytics-api"],
        "error_messages": [
            "java.lang.OutOfMemoryError: Java heap space",
            "Container killed with OOMKilled, rss=2.1GiB limit=2GiB",
            "GC overhead limit exceeded",
        ],
        "metric": "process_resident_memory_bytes",
        "spike_factor": 2.5,
        "root_cause": "Memory leak in request handler — unbounded cache growth",
        "fix": "Cap cache size and restart the service; investigate retained references",
    },
    "timeout_cascade": {
        "title": "Upstream timeout cascade",
        "services": ["checkout-api", "inventory-svc"],
        "error_messages": [
            "upstream request timeout after 30000ms",
            "504 Gateway Timeout from inventory-svc",
            "deadline exceeded calling inventory-svc/reserve",
        ],
        "metric": "http_request_duration_p95_ms",
        "spike_factor": 5.0,
        "root_cause": "Upstream timeout cascading from inventory-svc slowdown",
        "fix": "Add circuit breaker and reduce upstream timeout to fail fast",
    },
    "misconfiguration": {
        "title": "Bad config rolled out",
        "services": ["auth-svc"],
        "error_messages": [
            "config error: missing required env var JWT_SECRET",
            "invalid feature flag config: 'new_login_flow' = 'truee'",
            "ConfigParseError: malformed yaml in config map",
        ],
        "metric": "config_reload_errors_total",
        "spike_factor": 10.0,
        "root_cause": "Misconfiguration deployed — invalid feature flag value",
        "fix": "Revert config change and add schema validation in CI",
    },
    "dependency_failure": {
        "title": "Third-party dependency failure",
        "services": ["payment-api"],
        "error_messages": [
            "stripe.error.APIConnectionError: dns lookup failed",
            "TLS handshake failed against api.stripe.com",
            "downstream provider returned 503 Service Unavailable",
        ],
        "metric": "downstream_error_rate",
        "spike_factor": 8.0,
        "root_cause": "Third-party dependency (Stripe) outage",
        "fix": "Wait for upstream recovery; enable degraded-mode fallback",
    },
}


@dataclass
class SyntheticIncident:
    external_id: str
    category: str
    title: str
    services: list[str]
    started_at: datetime
    ended_at: datetime
    logs: list[dict]
    metrics: list[dict]
    deployments: list[dict]
    expected_root_cause: str
    expected_fix: str


def _generate_logs(blueprint: dict, services: list[str], start: datetime, end: datetime) -> list[dict]:
    logs: list[dict] = []
    duration = (end - start).total_seconds()
    n_errors = random.randint(40, 80)
    for i in range(n_errors):
        ts = start + timedelta(seconds=duration * (0.2 + 0.7 * (i / n_errors)))
        logs.append(
            {
                "service": random.choice(services),
                "level": "ERROR",
                "message": random.choice(blueprint["error_messages"]),
                "timestamp": ts,
                "attributes": {"trace_id": f"t-{i:04d}"},
            }
        )
    for _ in range(30):
        ts = start + timedelta(seconds=random.uniform(0, duration))
        logs.append(
            {
                "service": random.choice(services),
                "level": "INFO",
                "message": "request processed",
                "timestamp": ts,
                "attributes": {},
            }
        )
    return logs


def _generate_metrics(blueprint: dict, services: list[str], start: datetime, end: datetime) -> list[dict]:
    points: list[dict] = []
    duration = (end - start).total_seconds()
    n_points = 30
    baseline = random.uniform(50, 150)
    spike = baseline * blueprint["spike_factor"]
    spike_start = 0.3
    for i in range(n_points):
        frac = i / n_points
        ts = start + timedelta(seconds=duration * frac)
        if frac < spike_start:
            value = baseline + random.uniform(-10, 10)
        else:
            value = spike + random.uniform(-spike * 0.1, spike * 0.1)
        points.append(
            {
                "service": services[0],
                "name": blueprint["metric"],
                "value": value,
                "timestamp": ts,
                "labels": {},
            }
        )
    return points


def _generate_deployments(services: list[str], start: datetime) -> list[dict]:
    deploy_time = start - timedelta(minutes=random.randint(5, 45))
    return [
        {
            "service": services[0],
            "version": f"v{random.randint(2, 5)}.{random.randint(0, 9)}.{random.randint(0, 9)}",
            "deployer": random.choice(["alice", "bob", "carol", "automated-release"]),
            "description": "feature rollout + config update",
            "timestamp": deploy_time,
        }
    ]


def generate_incidents(n: int = 50, seed: int = 42) -> list[SyntheticIncident]:
    random.seed(seed)
    incidents: list[SyntheticIncident] = []
    for i in range(n):
        category = CATEGORIES[i % len(CATEGORIES)]
        blueprint = CATEGORY_BLUEPRINTS[category]
        start = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=i, hours=random.randint(0, 23))
        end = start + timedelta(minutes=random.randint(15, 90))
        services = blueprint["services"]
        incidents.append(
            SyntheticIncident(
                external_id=f"INC-EVAL-{i:04d}",
                category=category,
                title=blueprint["title"],
                services=services,
                started_at=start,
                ended_at=end,
                logs=_generate_logs(blueprint, services, start, end),
                metrics=_generate_metrics(blueprint, services, start, end),
                deployments=_generate_deployments(services, start),
                expected_root_cause=blueprint["root_cause"],
                expected_fix=blueprint["fix"],
            )
        )
    return incidents


def generate_postmortems(seed: int = 7) -> list[dict]:
    """A small library of historical postmortems for the RAG store."""
    random.seed(seed)
    postmortems = []
    templates = [
        ("db_pool_exhaustion", "Payments outage 2025-09-14",
         "DB pool exhausted at 10 connections under traffic spike",
         "Increased pool_size to 50 and added autoscaling alarm"),
        ("memory_leak", "Analytics OOM 2025-08-02",
         "Heap grew unbounded due to unflushed query cache",
         "Bounded the cache and added heap dump alerting"),
        ("timeout_cascade", "Checkout 504s 2025-07-19",
         "Inventory slowdown cascaded into checkout timeouts",
         "Introduced circuit breaker and shorter upstream timeouts"),
        ("misconfiguration", "Auth login failure 2025-06-08",
         "Bad feature flag value broke login flow",
         "Reverted flag and added config schema validation"),
        ("dependency_failure", "Stripe outage 2025-05-22",
         "Stripe API unavailable for 40 minutes",
         "Enabled graceful degradation and queued retries"),
        ("db_pool_exhaustion", "Worker stalls 2025-04-11",
         "Worker pool starved waiting on DB connections",
         "Tuned worker concurrency relative to pool size"),
        ("timeout_cascade", "Search latency 2025-03-05",
         "Search backend slowdown cascaded to API timeouts",
         "Added bulkhead pattern and read replica routing"),
    ]
    for i, (category, title, root_cause, resolution) in enumerate(templates):
        postmortems.append(
            {
                "external_id": f"INC-{2025 - i:04d}-{i:04d}",
                "title": title,
                "summary": f"{title}: {root_cause}",
                "root_cause": root_cause,
                "root_cause_category": category,
                "resolution": resolution,
                "occurred_at": datetime(2025, 1 + i % 12, 1, tzinfo=timezone.utc),
            }
        )
    return postmortems
