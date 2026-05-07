"""HTML dashboard — single-page, server-rendered, no frontend framework."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.api.auth import get_session
from src.billing import repository

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Render the operator dashboard."""
    subs = await repository.list_active_subscriptions(session)
    charges = await repository.list_recent_charges(session, limit=20)
    deliveries = await repository.list_recent_deliveries(session, limit=20)
    webhooks = await repository.list_webhooks(session)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "subscriptions": subs,
            "charges": charges,
            "deliveries": deliveries,
            "webhooks": webhooks,
        },
    )
