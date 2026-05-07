"""Application entrypoint — starts FastAPI + scheduler."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.api.billing_routes import router as billing_router
from src.api.dashboard_routes import router as dashboard_router
from src.billing.config import get_settings
from src.billing.db import dispose_db, init_db
from src.billing.scheduler import start_scheduler, stop_scheduler


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
    app.include_router(billing_router)
    app.include_router(dashboard_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        """Liveness probe."""
        return {"status": "ok"}

    return app


app = create_app()
