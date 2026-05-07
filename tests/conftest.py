"""Pytest fixtures — fresh in-memory DB per test."""

from __future__ import annotations

import os
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """ASGI client with a fresh in-memory DB and one bootstrapped API key."""
    # Reset module-level singletons between tests.
    from src.billing import db as db_mod
    from src.billing.config import get_settings

    db_mod._engine = None
    db_mod._sessionmaker = None
    get_settings.cache_clear()

    from src.api.auth import bootstrap_api_key
    from src.billing.db import init_db

    await init_db()
    _, api_key = await bootstrap_api_key("test")

    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.headers["Authorization"] = f"Bearer {api_key}"
        yield ac

    await db_mod.dispose_db()


@pytest.fixture
def valid_cpf() -> str:
    """A CPF that passes the check-digit algorithm."""
    return "11144477735"


@pytest.fixture
def valid_cnpj() -> str:
    """A CNPJ that passes the check-digit algorithm."""
    return "11222333000181"
