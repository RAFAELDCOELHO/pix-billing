"""API-key authentication and per-key rate limiting."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.billing import ids as id_gen
from src.billing import repository
from src.billing.config import get_settings
from src.billing.db import session_scope
from src.billing.models import ApiKey
from src.billing.security import hash_api_key

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Authenticated principal — passed into every protected endpoint."""

    api_key_id: str
    is_live: bool
    name: str


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a transactional session."""
    async with session_scope() as session:
        yield session


async def authenticate(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> AuthContext:
    """Validate an Authorization: Bearer pk_test_… header."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing api key")
    token = credentials.credentials
    if not token.startswith(("pk_test_", "pk_live_")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key prefix")
    record = await repository.find_api_key_by_hash(session, hash_api_key(token))
    if record is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid api key")
    ctx = AuthContext(api_key_id=record.id, is_live=record.is_live, name=record.name)
    request.state.auth = ctx
    return ctx


# ─── token-bucket rate limiter ─────────────────────────────────────────────


_buckets: dict[tuple[str, str], deque[float]] = defaultdict(deque)


def _check_bucket(scope: str, key_id: str, limit_per_min: int) -> None:
    now = time.monotonic()
    window = 60.0
    bucket = _buckets[(scope, key_id)]
    while bucket and now - bucket[0] > window:
        bucket.popleft()
    if len(bucket) >= limit_per_min:
        retry_after = int(window - (now - bucket[0])) + 1
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)


def enforce_customer_charge_limit(customer_id: str, limit_per_min: int = 10) -> None:
    """Anti-fraud: cap charge creation to ``limit_per_min`` per customer."""
    _check_bucket("charge_per_customer", customer_id, limit_per_min)


def rate_limit(
    scope: str, *, write: bool = False
) -> Callable[[AuthContext], Awaitable[AuthContext]]:
    """Return a FastAPI dependency enforcing per-key rate limits."""

    async def _dep(ctx: AuthContext = Depends(authenticate)) -> AuthContext:
        settings = get_settings()
        limit = settings.rate_limit_write_per_min if write else settings.rate_limit_read_per_min
        _check_bucket(scope, ctx.api_key_id, limit)
        return ctx

    return _dep


# ─── one-time bootstrap helper ─────────────────────────────────────────────


async def bootstrap_api_key(name: str, *, live: bool = False) -> tuple[str, str]:
    """Create an API key, persist its hash, return (id, plaintext)."""
    raw = id_gen.new_api_key(live=live)
    rec = ApiKey(
        id=id_gen.new_api_key_id(),
        name=name,
        key_hash=hash_api_key(raw),
        prefix=raw[:8],
        is_live=live,
        active=True,
    )
    async with session_scope() as session:
        await repository.create_api_key(session, rec)
    return rec.id, raw
