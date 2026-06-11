from prometheus_client import Counter, Gauge, Histogram

investigations_total = Counter(
    "investigations_total",
    "Total number of incident investigations triggered",
    ["status"],
)

investigation_duration_seconds = Histogram(
    "investigation_duration_seconds",
    "Duration of investigations in seconds",
    buckets=(1, 5, 10, 20, 30, 45, 60, 90, 120),
)

root_cause_confidence = Histogram(
    "root_cause_confidence",
    "Distribution of root cause confidence scores",
    buckets=(0.1, 0.25, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0),
)

agent_llm_calls_total = Counter(
    "agent_llm_calls_total",
    "Total LLM calls made by the agent",
    ["node", "model"],
)

agent_node_duration_seconds = Histogram(
    "agent_node_duration_seconds",
    "Duration of individual agent nodes",
    ["node"],
)

ingestion_records_total = Counter(
    "ingestion_records_total",
    "Records ingested",
    ["kind"],
)

eval_accuracy = Gauge(
    "eval_accuracy",
    "Latest evaluation root-cause exact match accuracy",
)
