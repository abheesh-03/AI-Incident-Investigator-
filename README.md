# AI Incident Investigator

[![CI](https://github.com/abheesh-03/AI-Incident-Investigator-/actions/workflows/ci.yml/badge.svg)](https://github.com/abheesh-03/AI-Incident-Investigator-/actions/workflows/ci.yml)

**Live demo:** <https://ai-incident-investigator-production.up.railway.app> ([`/health`](https://ai-incident-investigator-production.up.railway.app/health) · [`/metrics`](https://ai-incident-investigator-production.up.railway.app/metrics) · [`/docs`](https://ai-incident-investigator-production.up.railway.app/docs))

An AI-powered backend service that automatically investigates production
incidents by analyzing logs, metrics, and deployment history — and delivers
structured root cause hypotheses in under 60 seconds.

Built as a production-style backend platform demonstrating agentic AI
systems, RAG over operational data, LangGraph orchestration, and evaluation
frameworks for AI reliability.

---

## The Problem

When a production service fails, engineers spend 60–90 minutes manually:

- Scrolling through thousands of log lines across multiple services
- Staring at metric dashboards trying to find the anomaly window
- Checking recent deployments for changes that could have caused the failure
- Searching past incident docs to see if this pattern has occurred before

This project automates that investigation loop with an AI agent that
correlates signals across all four sources and delivers a structured,
explainable root cause hypothesis — with a confidence score.

---

## What It Does

```
Input:
  → Logs from affected services
  → Metric time-series data (latency, error rate, DB wait time, CPU)
  → Deployment history (what changed, when, by whom)

Output:
  {
    "root_cause": "DB connection pool exhaustion",
    "confidence": 0.87,
    "triggered_by": "Deployment v2.3.1 at 01:47 AM",
    "affected_services": ["payment-api", "transaction-worker"],
    "evidence": [...],
    "suggested_fix": "Roll back v2.3.1 or increase pool_size from 10 to 50",
    "similar_past_incidents": ["INC-2025-0914"]
  }
```

---

## Architecture

```
FastAPI (/ingest/*, /investigate, /investigations, /eval/report, /metrics)
    │
    ▼
LangGraph Agent
   log_analyzer  →  metric_correlator  →  root_cause_synthesizer
                                              │
                                              ▼
                                          pgvector RAG
                                          (past postmortems)
    │
    ▼
PostgreSQL + pgvector
(logs, metrics, deployments, incidents, investigations,
 incident_postmortems, audit_logs, eval_runs)
    │
    ▼
Prometheus + Grafana observability
```

---

## Tech Stack

| Layer                  | Technology                                          |
|------------------------|-----------------------------------------------------|
| Backend API            | FastAPI + Pydantic v2                               |
| Agent Orchestration    | LangGraph                                           |
| LLM                    | Claude (Anthropic SDK) with deterministic fallback  |
| RAG & Vector Search    | pgvector + Voyage AI embeddings (hash fallback)     |
| Database               | PostgreSQL 16 + Alembic                             |
| Observability          | Prometheus client + Grafana                         |
| Auth & Reliability     | JWT bearer auth, slowapi rate limiting, audit log   |
| Infrastructure         | Docker, Docker Compose, GitHub Actions CI          |

---

## How the Agent Works

### Node 1 — Log Analyzer
Fetches all logs in the incident window, ranks the most frequent error
patterns, and asks the LLM to identify the dominant pattern, anomaly onset
time, and an initial root cause hypothesis.

### Node 2 — Metric Correlator
Runs anomaly detection (z-score) over metric time-series, then asks the LLM
to correlate metric anomalies with the log patterns and recent deployments.

### Node 3 — Root Cause Synthesizer
Performs a pgvector cosine-similarity lookup over historical postmortems,
then feeds the combined context to the LLM to produce the final structured
hypothesis: root cause, category, confidence, triggered_by, evidence,
suggested fix, and similar past incidents.

Every node's inputs, duration, RAG hits, and outputs are persisted to the
`investigations.agent_trace` column — full auditability of every decision.

### Offline-friendly LLM
`app/core/llm.py` calls Claude via the Anthropic SDK when
`ANTHROPIC_API_KEY` is set. Otherwise it falls back to a deterministic
keyword-based responder so the agent (and the evaluation framework, and the
CI gate) run without an API key.

---

## Evaluation Framework

- **Dataset:** 50 synthetic incidents covering 5 categories (DB pool
  exhaustion, memory leak, timeout cascade, misconfiguration, dependency
  failure). Built by `eval/build_dataset.py`.
- **Evaluators:** Exact-match on root cause category + judge score on
  explanation overlap and category match (deterministic so CI is
  reproducible; swap in a real LLM judge for production).
- **CI Gate:** GitHub Actions runs `eval/run_eval.py` on every push — exits
  non-zero if accuracy falls below 75%.

---

## API Endpoints

```
POST   /auth/token                 Issue a JWT for an API key
POST   /ingest/logs                Ingest log entries
POST   /ingest/metrics             Ingest metric points
POST   /ingest/deployments         Ingest deployment events
POST   /investigate                Trigger investigation for an incident
GET    /investigations/{id}        Get investigation result
GET    /investigations             List recent investigations
GET    /eval/report                Latest evaluation report
GET    /health                     Health check
GET    /metrics                    Prometheus scrape target
```

All endpoints (except `/auth/token`, `/health`, `/metrics`) require a
bearer JWT. Rate limiting is applied per token.

---

## Deployment (Railway)

The repo includes `railway.json` and a Dockerfile that runs migrations on
startup, so deploying is a few clicks:

1. Create a Railway project from this GitHub repo (Railway auto-detects the
   Dockerfile and `railway.json`).
2. Add a **Postgres + pgvector** plugin to the project (Railway's
   "PostgreSQL" template includes pgvector — confirm via
   `CREATE EXTENSION vector;`).
3. In the API service's variables, set:
   - `DATABASE_URL` → reference the Postgres plugin's `DATABASE_URL`
     and prefix it with `postgresql+psycopg://` (Railway gives you
     `postgresql://...`; psycopg3 needs the explicit driver).
   - `JWT_SECRET` → any long random string.
   - `ANTHROPIC_API_KEY` → your Anthropic key.
   - `LLM_MODEL` → optional, defaults to `claude-haiku-4-5-20251001`.
4. Railway runs `alembic upgrade head` on each deploy, then starts uvicorn
   on `$PORT`. Health check hits `/health`.
5. Once the deploy is green, seed historical postmortems and (optionally)
   synthetic incidents:

   ```bash
   railway run python scripts/seed_incidents.py
   ```

The same recipe works on Render / Fly.io — the Dockerfile is portable.

---

## Running Locally

### With Docker (recommended)

```bash
git clone https://github.com/abheesh-03/ai-incident-investigator
cd ai-incident-investigator
cp .env.example .env
docker compose up --build
# In another shell, seed synthetic data:
docker compose exec api python scripts/seed_incidents.py
```

API at <http://localhost:8000> · Prometheus at <http://localhost:9090> ·
Grafana at <http://localhost:3000> (admin/admin).

### Without Docker

```bash
pip install -r requirements.txt
# Point DATABASE_URL at a Postgres with the pgvector extension installed.
alembic upgrade head
python scripts/seed_incidents.py
uvicorn app.main:app --reload
```

### Run the evaluation

```bash
python eval/build_dataset.py
python eval/run_eval.py     # exits non-zero if accuracy < 75%
```

---

## Quick demo

```bash
# 1. Get a token
TOKEN=$(curl -s -X POST localhost:8000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"api_key":"demo-key"}' | jq -r .access_token)

# 2. Trigger an investigation (after seeding)
curl -s -X POST localhost:8000/investigate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "external_id": "INC-DEMO-001",
    "title": "Payments down",
    "started_at": "2026-01-01T01:47:00Z",
    "affected_services": ["payment-api"]
  }'

# 3. Read the result
curl -s localhost:8000/investigations/1 -H "Authorization: Bearer $TOKEN" | jq
```

---

## Project Structure

```
app/
  agent/
    graph.py                # LangGraph definition
    runner.py               # Pulls inputs from DB and persists results
    rag.py                  # pgvector postmortem retrieval
    state.py                # InvestigationState TypedDict
    nodes/
      log_analyzer.py
      metric_correlator.py
      root_cause_synthesizer.py
  api/
    auth.py                 # JWT issuance
    ingest.py               # Log/metric/deployment ingestion
    investigate.py          # Trigger + retrieve investigations
    eval.py                 # Eval report endpoint
    schemas.py              # Pydantic request/response models
  core/
    config.py               # Settings (env-driven)
    auth.py                 # JWT verification dependency
    llm.py                  # Anthropic SDK + deterministic fallback
    embeddings.py           # Voyage AI + deterministic hash fallback
    anomaly_detector.py     # Z-score anomaly detection
    metrics.py              # Prometheus instruments
  db/
    models.py               # SQLAlchemy models (8 tables)
    session.py
    migrations/             # Alembic
  main.py
eval/
  build_dataset.py
  run_eval.py
  dataset/incidents.json    # Generated; 50 labeled synthetic incidents
scripts/
  synth.py                  # Synthetic data generator (shared by eval+seed)
  seed_incidents.py
tests/
  test_health.py, test_auth.py, test_ingest.py,
  test_agent.py, test_investigate_api.py
grafana/                    # Provisioned dashboard
prometheus.yml
docker-compose.yml
Dockerfile
.github/workflows/ci.yml
alembic.ini
```

---

## What This Demonstrates

**Backend engineering**
- Layered FastAPI service with Pydantic v2 validation, JWT auth, and rate
  limiting
- 8-table PostgreSQL schema with Alembic migrations and pgvector
- Background-task driven async investigation flow with full audit logging
- Docker Compose with Postgres + Prometheus + Grafana provisioned

**Applied AI engineering**
- Three-node LangGraph agent with stateful orchestration and per-node
  tracing
- RAG pipeline over historical postmortems using pgvector cosine distance
- Structured LLM outputs with category constraint + confidence scoring
- Deterministic LLM + embedding fallbacks so the whole system runs offline
- Evaluation framework with labeled dataset, judge score, and CI accuracy
  gate

---

## Author

**Sai Abheesh Annaiah**

[github.com/abheesh-03](https://github.com/abheesh-03) · abheesh20.a@gmail.com
