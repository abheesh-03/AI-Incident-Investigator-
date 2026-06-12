from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api import auth as auth_api
from app.api import eval as eval_api
from app.api import ingest as ingest_api
from app.api import investigate as investigate_api
from app.core.config import get_settings

settings = get_settings()
logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


def _rate_key(request: Request) -> str:
    # Prefer the JWT subject if present; fall back to remote address.
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:][:64]
    return get_remote_address(request)


limiter = Limiter(
    key_func=_rate_key,
    default_limits=[f"{settings.rate_limit_per_minute}/minute"],
)


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Incident Investigator",
        version="0.1.0",
        description=(
            "Investigates production incidents by correlating logs, metrics, and "
            "deployment history via a LangGraph agent."
        ),
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    app.include_router(auth_api.router)
    app.include_router(ingest_api.router)
    app.include_router(investigate_api.router)
    app.include_router(eval_api.router)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/docs")

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics", tags=["meta"])
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
