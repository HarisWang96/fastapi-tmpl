"""Service-side policy enforcement points (PEP).

Authentication and coarse route admission stay at the gateway. Fine-grained
authorization lives here because it needs the caller identity plus business
context (resource ownership, department/store/warehouse scope) that the gateway
does not have. Internal calls, scheduled jobs and exports also bypass the
gateway, so resources must be guarded at the service boundary.

Usage:
    @router.get("/products")
    async def list_products(
        caller: Annotated[Caller, Depends(require_perm("product:read"))],
        scope: Annotated[DataScope, Depends(require_scope("product", "store"))],
    ): ...
"""

import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import Depends

from app.api.deps import Caller, RequiredCallerDep
from app.clients.authz import AuthzClient, DataScope, Decision
from app.core.config import settings
from app.core.exceptions import AuthError, ForbiddenError, ServiceUnavailableError
from app.core.logger import logger

_authz_client: AuthzClient | None = None


def get_authz_client() -> AuthzClient:
    global _authz_client
    if _authz_client is None:
        token = settings.INTERNAL_API_TOKEN
        if token is None:
            raise ServiceUnavailableError("未配置 INTERNAL_API_TOKEN")
        _authz_client = AuthzClient(
            base_url=settings.AUTHZ_BASE_URL,
            internal_token=token.get_secret_value(),
            timeout=settings.AUTHZ_TIMEOUT_SECONDS,
        )
    return _authz_client


AuthzClientDep = Annotated[AuthzClient, Depends(get_authz_client)]


async def close_authz_client() -> None:
    global _authz_client
    if _authz_client is not None:
        await _authz_client.aclose()
        _authz_client = None


class _TtlCache:
    """Small in-process cache; TTL bounds staleness after a permission change.

    authz-svc bumps a per-user version on grant/revoke. Reading that version on
    every request costs an extra RPC, so this skeleton uses a short TTL instead.
    The tradeoff is explicit: a revoked permission can remain effective for at
    most AUTHZ_CACHE_TTL_SECONDS. Set it to 0 when revocation must be immediate.
    """

    _MAX_ENTRIES = 10_000

    def __init__(self) -> None:
        self._items: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def get(self, key: tuple[Any, ...]) -> Any | None:
        item = self._items.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            self._items.pop(key, None)
            return None
        return value

    def set(self, key: tuple[Any, ...], value: Any) -> None:
        ttl = settings.AUTHZ_CACHE_TTL_SECONDS
        if ttl <= 0:
            return
        if len(self._items) >= self._MAX_ENTRIES:
            self._items.pop(next(iter(self._items)))
        self._items[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._items.clear()


_decision_cache = _TtlCache()
_scope_cache = _TtlCache()


def reset_authz_cache() -> None:
    """Test helper; production processes never need to clear the cache manually."""
    _decision_cache.clear()
    _scope_cache.clear()


def _require_app_id(caller: Caller) -> str:
    if caller.app_id is None:
        raise AuthError("缺少网关身份头 X-App-Id")
    return caller.app_id


def require_perm(perm_code: str) -> Callable[..., Awaitable[Caller]]:
    """Require a permission code for this route; raises 403/503 on failure."""

    async def dependency(caller: RequiredCallerDep, client: AuthzClientDep) -> Caller:
        app_id = _require_app_id(caller)
        user_id = int(caller.user_id)  # RequiredCallerDep guarantees non-None.
        key = (user_id, app_id, perm_code)
        decision: Decision | None = _decision_cache.get(key)
        if decision is None:
            decision = await client.check(user_id=user_id, app_id=app_id, perm_code=perm_code)
            _decision_cache.set(key, decision)
        if not decision.allow:
            logger.warning(
                f"权限拒绝 user={user_id} app={app_id} perm={perm_code} reason={decision.reason}"
            )
            raise ForbiddenError()
        return caller

    return dependency


def require_scope(resource_key: str, dimension: str) -> Callable[..., Awaitable[DataScope]]:
    """Resolve the caller's data scope; services turn values into WHERE clauses."""

    async def dependency(caller: RequiredCallerDep, client: AuthzClientDep) -> DataScope:
        app_id = _require_app_id(caller)
        user_id = int(caller.user_id)
        key = (user_id, app_id, resource_key, dimension)
        scope: DataScope | None = _scope_cache.get(key)
        if scope is None:
            scope = await client.scope(
                user_id=user_id,
                app_id=app_id,
                resource_key=resource_key,
                dimension=dimension,
            )
            _scope_cache.set(key, scope)
        return scope

    return dependency
