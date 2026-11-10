"""Common request dependencies for database, Redis, and gateway identity headers.

This service does not parse JWTs. The gateway (auth service) authenticates
requests and writes these identity headers for downstream services:
- `X-User-Id`: caller user ID (integer)
- `X-App-Id`: caller application identifier
- `X-Proxy-Token`: optional; required when TRUSTED_PROXY_TOKEN is configured

Clients can forge these headers, so NetworkPolicy must restrict ingress to the
gateway. X-Proxy-Token is defense in depth and does not replace network policy.
"""

import hmac
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header
from pydantic import BaseModel
from redis import StrictRedis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.mysql import MysqlConnection, mysql_pool
from app.core.db.orm import get_session_factory
from app.core.db.redis import get_redis
from app.core.exceptions import AuthError, ServiceUnavailableError


def get_db() -> Iterator[MysqlConnection]:
    """Yield one connection per request, rolling back errors and returning it to the pool.

    This commit is only a fallback and runs after the response is sent. Write
    handlers must commit before returning so a 200 response means data is stored.
    """
    conn = mysql_pool.connection("default")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Use raw SQL only for queries that are impractical to express with the ORM.
DbSession = Annotated[MysqlConnection, Depends(get_db)]


def get_session() -> Iterator[Session]:
    """Yield an ORM session, rolling back errors and closing it after the request.

    Commit is only a fallback and runs after the response; write handlers must
    explicitly commit before returning.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_redis_client() -> StrictRedis:
    return get_redis()


RedisClient = Annotated[StrictRedis, Depends(get_redis_client)]


class Caller(BaseModel):
    """Caller identity injected by the authenticated gateway."""

    user_id: int | None = None
    app_id: str | None = None


def _check_proxy_token(token: str | None) -> None:
    expected = settings.TRUSTED_PROXY_TOKEN
    if expected is None:
        return
    # Compare bytes because a non-ASCII request header would make str comparison raise TypeError.
    if not token or not hmac.compare_digest(
        token.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise AuthError("代理令牌无效或缺失")


async def get_caller(
    x_user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    x_app_id: Annotated[str | None, Header(alias="X-App-Id")] = None,
    x_proxy_token: Annotated[str | None, Header(alias="X-Proxy-Token")] = None,
) -> Caller:
    """Allow public endpoints; missing identity headers produce None values."""
    _check_proxy_token(x_proxy_token)
    user_id: int | None = None
    if x_user_id:
        try:
            user_id = int(x_user_id)
        except ValueError as exc:
            raise AuthError("X-User-Id 非法") from exc
    return Caller(user_id=user_id, app_id=x_app_id or None)


async def require_caller(caller: Annotated[Caller, Depends(get_caller)]) -> Caller:
    """Use this dependency for endpoints that require a caller identity."""
    if caller.user_id is None:
        raise AuthError("缺少网关身份头 X-User-Id")
    return caller


CallerDep = Annotated[Caller, Depends(get_caller)]
RequiredCallerDep = Annotated[Caller, Depends(require_caller)]

def require_internal_token(
    x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
) -> None:
    """Guard service-to-service endpoints; callers must present INTERNAL_API_TOKEN."""
    expected = settings.INTERNAL_API_TOKEN
    if expected is None:
        raise ServiceUnavailableError("未配置 INTERNAL_API_TOKEN")
    if not x_internal_token or not hmac.compare_digest(
        x_internal_token.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise AuthError("内部令牌无效或缺失")


InternalTokenDep = Annotated[None, Depends(require_internal_token)]
