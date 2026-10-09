from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from prometheus_client import Counter, Histogram, start_http_server

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
from darkpulse.api.routes.alerts import start_alert_relay, stop_alert_relay
from darkpulse.api.security import bind_session_store, close_session_store, current_principal
from darkpulse.broker.processor import MongoProcessor
from darkpulse.config import allowed_origins, enforce_boot, get_settings
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


_metrics_started = False


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    enforce_boot(settings)
    global _metrics_started
    if settings.service.metrics_port and not _metrics_started:
        start_http_server(settings.service.metrics_port)
        _metrics_started = True
    app.state.settings = settings
    bind_session_store(settings.redis.url)
    await start_alert_relay(settings.redis.url)
    app.state.mongo = MongoManager(settings.mongo)
    app.state.neo4j = Neo4jManager(settings.neo4j)

    await app.state.mongo.connect()
    await app.state.mongo.ensure_application_defaults(settings.slang.seed_dictionary)
    try:
        await app.state.neo4j.connect()
    except Exception:
        logger.exception("neo4j.connect_failed")

    from darkpulse.ingestion.dedup import RedisDedupStore

    dedup = RedisDedupStore(
        settings.redis.url, ttl_seconds=settings.collection.dedup_ttl_seconds
    )
    app.state.processor = MongoProcessor(settings, app.state.mongo, app.state.neo4j, dedup=dedup)
    await app.state.processor.start()

    yield

    await stop_alert_relay()
    close_session_store()
    await app.state.processor.stop()
    await app.state.mongo.close()
    await app.state.neo4j.close()


_docs_enabled = get_settings().auth.local_open_mode
app = FastAPI(
    title="DarkPulse Investigator API",
    version=SERVICE_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url=None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins(get_settings())),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-DarkPulse-Evidence-Seal", "X-Trace-ID"],
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
app.include_router(alerts.ws_router, prefix="/api/v1")
app.include_router(export.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(evidence.router, prefix="/api/v1", dependencies=_authenticated)
app.include_router(operations.router, prefix="/api/v1", dependencies=_authenticated)


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
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
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
    logger.error(
        "api.unhandled_error",
        path=request.url.path,
        error_type=type(exc).__name__,
        exc_info=exc,
    )
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


@app.exception_handler(404)
async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        request, status_code=404, code="not_found", message="Not found"
    )


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc: Exception) -> JSONResponse:
    return _error_response(
        request, status_code=405, code="method_not_allowed", message="Method not allowed"
    )


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    target = get_settings().service.frontend_origin
    if target.startswith("http"):
        return RedirectResponse(target, status_code=302)
    return RedirectResponse("/health", status_code=302)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/health")
async def api_health() -> JSONResponse:
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

    def _status_of(payload: object) -> str:
        if not isinstance(payload, dict):
            return ""
        return str(payload.get("status", "")).lower()

    ready = (
        _status_of(mongo_health) in healthy_states
        and _status_of(neo4j_health) in healthy_states
        and processor_healthy
    )
    all_healthy = ready and _status_of(collector_health) == "healthy"
    body = {
        "status": "healthy" if all_healthy else "degraded",
        "services": {
            "mongodb": mongo_health if isinstance(mongo_health, dict) else {"status": "unhealthy"},
            "neo4j": neo4j_health if isinstance(neo4j_health, dict) else {"status": "unhealthy"},
            "processor": {"status": "healthy" if processor_healthy else "unhealthy"},
            "collector": collector_health,
        },
    }
    return JSONResponse(status_code=200 if ready else 503, content=body)


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
