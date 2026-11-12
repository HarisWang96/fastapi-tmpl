"""Common async request dependencies."""

import hmac
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.authz import AuthzClient, DataScope, Decision
from app.config import settings
from app.database import get_db
from app.errors import ForbiddenError, ServiceUnavailableError, UnauthorizedError


class Caller(BaseModel):
    user_id: int | None = None
    app_id: str | None = None


async def get_caller(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_app_id: Annotated[str | None, Header(alias="X-App-Id")] = None,
    x_proxy_token: Annotated[str | None, Header(alias="X-Proxy-Token")] = None,
) -> Caller:
    if not settings.AUTH_ENABLED:
        raise ServiceUnavailableError("Identity authentication is not enabled")
    expected = settings.TRUSTED_PROXY_TOKEN
    if expected and (
        not x_proxy_token
        or not hmac.compare_digest(x_proxy_token, expected.get_secret_value())
    ):
        raise UnauthorizedError("Invalid proxy token")
    try:
        user_id = int(x_user_id) if x_user_id else None
    except ValueError as exc:
        raise UnauthorizedError("Invalid X-User-Id") from exc
    return Caller(user_id=user_id, app_id=x_app_id)


async def require_caller(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    if caller.user_id is None or caller.app_id is None:
        raise UnauthorizedError("Missing caller identity")
    return caller


CallerDep = Annotated[Caller, Depends(get_caller)]
RequiredCallerDep = Annotated[Caller, Depends(require_caller)]
AsyncSessionDep = Annotated[AsyncSession, Depends(get_db)]

_authz: AuthzClient | None = None


def get_authz_client() -> AuthzClient:
    global _authz
    if not settings.AUTHZ_ENABLED:
        raise ServiceUnavailableError("Authorization integration is not enabled")
    if _authz is None:
        if settings.INTERNAL_API_TOKEN is None:
            raise ServiceUnavailableError("INTERNAL_API_TOKEN is not configured")
        _authz = AuthzClient(
            settings.AUTHZ_BASE_URL,
            settings.INTERNAL_API_TOKEN.get_secret_value(),
            settings.AUTHZ_TIMEOUT_SECONDS,
        )
    return _authz


async def close_authz_client() -> None:
    global _authz
    if _authz:
        await _authz.aclose()
        _authz = None


class _Cache:
    def __init__(self) -> None:
        self.items: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def get(self, key: tuple[Any, ...]) -> Any | None:
        item = self.items.get(key)
        if not item:
            return None
        if item[0] <= time.monotonic():
            self.items.pop(key, None)
            return None
        return item[1]

    def set(self, key: tuple[Any, ...], value: Any) -> None:
        ttl = settings.AUTHZ_CACHE_TTL_SECONDS
        if ttl <= 0:
            return
        if len(self.items) >= 10000:
            self.items.pop(next(iter(self.items)))
        self.items[key] = (time.monotonic() + ttl, value)


_decision_cache = _Cache()
_scope_cache = _Cache()


def require_perm(code: str) -> Callable[..., Awaitable[Caller]]:
    async def dependency(
        caller: RequiredCallerDep,
        client: Annotated[AuthzClient, Depends(get_authz_client)],
    ) -> Caller:
        key = (caller.user_id, caller.app_id, code)
        decision: Decision | None = _decision_cache.get(key)
        if decision is None:
            decision = await client.check(
                user_id=caller.user_id, app_id=caller.app_id, perm_code=code
            )
            _decision_cache.set(key, decision)
        if not decision.allow:
            raise ForbiddenError()
        return caller

    return dependency


def require_scope(
    resource_key: str, dimension: str
) -> Callable[..., Awaitable[DataScope]]:
    async def dependency(
        caller: RequiredCallerDep,
        client: Annotated[AuthzClient, Depends(get_authz_client)],
    ) -> DataScope:
        key = (caller.user_id, caller.app_id, resource_key, dimension)
        scope: DataScope | None = _scope_cache.get(key)
        if scope is None:
            scope = await client.scope(
                user_id=caller.user_id,
                app_id=caller.app_id,
                resource_key=resource_key,
                dimension=dimension,
            )
            _scope_cache.set(key, scope)
        return scope

    return dependency
