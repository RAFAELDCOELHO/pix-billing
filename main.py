"""Application entrypoint — starts FastAPI + scheduler."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from src.api.billing_routes import router as billing_router
from src.api.dashboard_routes import router as dashboard_router
from src.api.security_headers import SecurityHeadersMiddleware
from src.billing.config import get_settings
from src.billing.db import dispose_db, init_db
from src.billing.scheduler import start_scheduler, stop_scheduler

log = logging.getLogger("pix_billing.app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Bring up the DB schema and the scheduler; tear them down at shutdown."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    await init_db()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()
        await dispose_db()


def create_app() -> FastAPI:
    """FastAPI app factory."""
    app = FastAPI(
        title="PIX Billing Stack",
        version="0.1.0",
        description="Open-source billing API for Brazilian PIX payments.",
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(billing_router)
    app.include_router(dashboard_router)

    @app.exception_handler(Exception)
    async def _scrub_unhandled(request: Request, exc: Exception) -> JSONResponse:
        """Never leak stack traces or DB errors to clients."""
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": "an unexpected error occurred"},
        )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    return app


app = create_app()
