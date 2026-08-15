from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app

from darkpulse.api.rate_limit import enforce_write_rate_limit
from darkpulse.api.routes import (
    actors,
    alerts,
    auth,
    dashboards,
    evidence,
    export,
    graph,
    intel,
    operations,
    search,
    slang,
    watchlists,
)
from darkpulse.api.security import current_principal
from darkpulse.broker.processor import MongoProcessor
from darkpulse.config import get_settings
from darkpulse.storage.mongodb import MongoManager
from darkpulse.storage.neo4j import Neo4jManager

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

SERVICE_NAME = "darkpulse"
SERVICE_VERSION = "1.0.0"

API_REQUESTS = Counter(
    "darkpulse_api_requests_total",
    "Investigator API requests",
    ("method", "path", "status"),
)
API_LATENCY = Histogram(
    "darkpulse_api_request_duration_seconds",
    "Investigator API request duration",
    ("method", "path"),
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    if settings.service.environment == "production":
        if not settings.auth.enabled or not settings.auth.tokens_json:
            raise RuntimeError(
                "Production requires DARKPULSE_AUTH_ENABLED and DARKPULSE_AUTH_TOKENS_JSON; "
                "use an OIDC gateway for managed identity."
            )
        if settings.neo4j.password == "darkpulse_dev":
            raise RuntimeError("Production requires a non-default Neo4j password (NEO4J_PASSWORD).")
        if not settings.service.frontend_origin.startswith("https://"):
            raise RuntimeError(
                "Production requires an HTTPS frontend origin (DARKPULSE_FRONTEND_ORIGIN)."
            )
    app.state.settings = settings
    app.state.mongo = MongoManager(settings.mongo)
    app.state.neo4j = Neo4jManager(settings.neo4j)

    await app.state.mongo.connect()
    await app.state.mongo.ensure_application_defaults(settings.slang.seed_dictionary)
    try:
        await app.state.neo4j.connect()
    except Exception:
        logger.exception("neo4j.connect_failed")

    app.state.processor = MongoProcessor(settings, app.state.mongo, app.state.neo4j)
    await app.state.processor.start()

    yield

    await app.state.processor.stop()
    await app.state.mongo.close()
    await app.state.neo4j.close()


app = FastAPI(
    title="DarkPulse — Investigator API",
    description="DarkPulse intelligence API serving the investigator dashboard",
    version=SERVICE_VERSION,
    lifespan=lifespan,
)

environment = os.environ.get("DARKPULSE_ENVIRONMENT", "development")
frontend_origin = os.environ.get("DARKPULSE_FRONTEND_ORIGIN", "http://localhost:5173")

allowed_origins = (
    ["http://localhost:5173", "http://localhost:3000"]
    if environment == "development"
    else [frontend_origin]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_authenticated = [Depends(current_principal), Depends(enforce_write_rate_limit)]
app.include_router(auth.router, prefix="/api/v1", dependencies=[Depends(enforce_write_rate_limit)])
app.include_router(intel.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(actors.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(graph.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(search.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(dashboards.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(watchlists.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(slang.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(alerts.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(export.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(evidence.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(operations.router, prefix="/api/v1", dependencies=_authenticated)
app.mount("/metrics", make_asgi_app())


@app.middleware("http")
async def request_context(request: Request, call_next: Any) -> Any:
    trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
    request.state.trace_id = trace_id
    started = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    route_path = getattr(route, "path", request.url.path)
    API_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
    API_LATENCY.labels(request.method, route_path).observe(time.perf_counter() - started)
    response.headers["X-Trace-ID"] = trace_id
    return response


def _error_response(request: Request, *, status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "data": None,
            "meta": {},
            "errors": [
                {
                    "code": code,
                    "message": message,
                    "trace_id": getattr(request.state, "trace_id", None),
                }
            ],
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("api.unhandled_error", path=request.url.path, error_type=type(exc).__name__)
    return _error_response(
        request, status_code=500, code="internal_error", message="Internal server error"
    )


_STATUS_CODES = {
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return _error_response(
        request,
        status_code=exc.status_code,
        code=_STATUS_CODES.get(exc.status_code, "http_error"),
        message=str(exc.detail),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    logger.info(
        "api.request_validation_failed",
        path=request.url.path,
        error_count=len(exc.errors()),
    )
    return _error_response(
        request,
        status_code=422,
        code="request_validation_failed",
        message="Request validation failed",
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "healthy", "service": SERVICE_NAME, "version": SERVICE_VERSION}


@app.get("/api/v1/health")
async def api_health() -> dict[str, Any]:
    mongo_health = (
        await app.state.mongo.health()
        if hasattr(app.state, "mongo")
        else {"status": "uninitialized"}
    )
    neo4j_health = (
        await app.state.neo4j.health()
        if hasattr(app.state, "neo4j")
        else {"status": "uninitialized"}
    )
    processor_healthy = (
        app.state.processor.healthy if getattr(app.state, "processor", None) is not None else False
    )
    collector_health: dict[str, Any] = {"status": "unknown"}
    try:
        latest_run = (
            await app.state.mongo.collection_runs.find({})
            .sort("started_at", -1)
            .limit(1)
            .to_list(length=1)
        )
        if latest_run:
            latest = latest_run[0]
            started = latest.get("started_at")
            collector_health = {
                "status": "failed" if latest.get("failure_code") else "healthy",
                "last_started_at": started.isoformat()
                if hasattr(started, "isoformat")
                else started,
                "source_id": latest.get("source_id"),
            }
        else:
            collector_health = {"status": "never_run"}
    except Exception:
        collector_health = {"status": "unknown"}

    healthy_states = {"healthy", "green", "yellow"}
    all_healthy = (
        all(
            str(h.get("status", "")).lower() in healthy_states for h in [mongo_health, neo4j_health]
        )
        and processor_healthy
    )

    return {
        "status": "healthy" if all_healthy else "degraded",
        "services": {
            "mongodb": mongo_health,
            "neo4j": neo4j_health,
            "processor": {"status": "healthy" if processor_healthy else "unhealthy"},
            "collector": collector_health,
        },
    }


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "darkpulse.api.app:app",
        host=settings.service.api_host,
        port=settings.service.api_port,
        reload=False,
        log_level=settings.service.log_level.lower(),
    )
