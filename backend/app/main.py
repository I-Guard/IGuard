"""IGuard FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import install_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.database.session import get_engine
from app.integrations import Integrations
from app.middleware.request_context import RequestContextMiddleware
from app.workers.loops import WorkerManager, startup_sync

log = get_logger("iguard")


def create_app(integrations: Integrations | None = None, *, run_startup: bool = True) -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.service_name, settings.env)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        integ = integrations or Integrations.build_default()
        app.state.integrations = integ
        manager: WorkerManager | None = None
        if run_startup:
            startup_sync()
        if settings.workers_enabled:
            manager = WorkerManager(integ)
            manager.start()
        log.info("iguard started", extra={"version": __version__})
        try:
            yield
        finally:
            log.info("iguard shutting down")
            if manager:
                manager.shutdown()
            if integrations is None:
                integ.close()
            get_engine().dispose()

    app = FastAPI(
        title="IGuard API",
        version=__version__,
        lifespan=lifespan,
        description="iGaming Infrastructure Guardian - Monitor. Detect. Recover. Protect.",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )
    # Tests build the app without entering lifespan; make integrations available immediately.
    app.state.integrations = integrations or Integrations.build_default()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-CSRF-Token",
            "X-Request-ID",
            "X-Correlation-ID",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-ID", "Idempotent-Replay"],
    )
    app.add_middleware(RequestContextMiddleware, hsts=settings.cookie_secure)
    install_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {"name": "IGuard", "docs": "/docs", "api": "/api/v1"}

    return app


# Uvicorn owns SIGTERM/SIGINT and triggers the lifespan shutdown (workers stop, pool disposes).
app = create_app()
