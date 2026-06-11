from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LogIn(BaseModel):
    service: str
    level: str = Field(pattern="^(DEBUG|INFO|WARN|ERROR|FATAL)$")
    message: str
    timestamp: datetime
    attributes: dict[str, Any] = Field(default_factory=dict)


class MetricIn(BaseModel):
    service: str
    name: str
    value: float
    timestamp: datetime
    labels: dict[str, Any] = Field(default_factory=dict)


class DeploymentIn(BaseModel):
    service: str
    version: str
    deployer: str
    description: str = ""
    timestamp: datetime


class IngestResponse(BaseModel):
    ingested: int


class InvestigateRequest(BaseModel):
    external_id: str
    title: str
    started_at: datetime
    ended_at: datetime | None = None
    affected_services: list[str] = Field(default_factory=list)


class InvestigationOut(BaseModel):
    id: int
    incident_id: int
    status: str
    root_cause: str | None
    root_cause_category: str | None
    confidence: float | None
    triggered_by: str | None
    suggested_fix: str | None
    evidence: list[Any]
    similar_past_incidents: list[Any]
    duration_seconds: float | None
    agent_trace: list[Any]
    error: str | None
    created_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class InvestigationSummary(BaseModel):
    id: int
    incident_id: int
    status: str
    root_cause_category: str | None
    confidence: float | None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenRequest(BaseModel):
    api_key: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
