"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

from app.core.config import get_settings

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

settings = get_settings()


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service", sa.String(128), index=True, nullable=False),
        sa.Column("level", sa.String(16), index=True, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_logs_service_ts", "logs", ["service", "timestamp"])

    op.create_table(
        "metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service", sa.String(128), index=True, nullable=False),
        sa.Column("name", sa.String(128), index=True, nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), index=True, nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False, server_default="{}"),
    )
    op.create_index("ix_metrics_service_name_ts", "metrics", ["service", "name", "timestamp"])

    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("service", sa.String(128), index=True, nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("deployer", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("timestamp", sa.DateTime(timezone=True), index=True, nullable=False),
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("external_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("affected_services", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "investigations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("incident_id", sa.Integer(), sa.ForeignKey("incidents.id"), index=True, nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("root_cause_category", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("triggered_by", sa.Text(), nullable=True),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("similar_past_incidents", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("agent_trace", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "incident_postmortems",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("external_id", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=False),
        sa.Column("root_cause_category", sa.String(64), index=True, nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False, server_default=""),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("embedding", Vector(settings.embedding_dim), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor", sa.String(128), index=True, nullable=False),
        sa.Column("action", sa.String(128), index=True, nullable=False),
        sa.Column("resource", sa.String(256), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now(), index=True),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("dataset_size", sa.Integer(), nullable=False),
        sa.Column("exact_match_accuracy", sa.Float(), nullable=False),
        sa.Column("judge_score", sa.Float(), nullable=False),
        sa.Column("mean_duration_seconds", sa.Float(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    for table in (
        "eval_runs",
        "audit_logs",
        "incident_postmortems",
        "investigations",
        "incidents",
        "deployments",
        "metrics",
        "logs",
    ):
        op.drop_table(table)
