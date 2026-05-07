"""HTML dashboard — single-page, server-rendered, no frontend framework."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.api.auth import get_session
from src.billing import repository
from src.billing.security import hash_api_key

router = APIRouter()
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "dashboard" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_basic = HTTPBasic(auto_error=False, realm="pix-billing")


async def _dashboard_auth(
    credentials: HTTPBasicCredentials | None = Depends(_basic),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Gate the dashboard with HTTP Basic — password must be a valid API key."""
    if credentials is None or not credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": 'Basic realm="pix-billing"'},
        )
    token = credentials.password
    if not token.startswith(("pk_test_", "pk_live_")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": 'Basic realm="pix-billing"'},
        )
    record = await repository.find_api_key_by_hash(session, hash_api_key(token))
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
            headers={"WWW-Authenticate": 'Basic realm="pix-billing"'},
        )
    return record.id


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def dashboard(
    request: Request,
    session: AsyncSession = Depends(get_session),
    _: str = Depends(_dashboard_auth),
) -> Response:
    """Render the operator dashboard. HTTP Basic — password = API key."""
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
