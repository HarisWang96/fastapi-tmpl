"""Request-level idempotency for write endpoints.

Clients send `Idempotency-Key` on a POST/PUT/PATCH. The first request executes
and stores its response; a retry with the same key and body returns the stored
response instead of applying the write twice. A different body under the same
key is rejected with 409, and a concurrent duplicate while the first request is
still running is also 409.

The key is scoped to caller + method + path, so one key can be reused on
different routes without colliding.

Usage:
    @router.post("/orders")
    @idempotent(required=True)
    def create_order(request: Request, ...): ...
"""

from __future__ import annotations

import asyncio
import base64
import functools
import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, TypeVar

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.core.clock import now
from app.core.config import settings
from app.core.db.orm import get_session_factory
from app.core.exceptions import BadRequestError, ConflictError
from app.core.logger import logger
from app.models.platform import IdempotencyRecord

_IN_PROGRESS = 1
_COMPLETED = 2
_MAX_KEY_LENGTH = 128

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: Any


class IdempotencyStore:
    """Persistence for idempotency records; independent of the request transaction."""

    def __init__(self, session_factory: sessionmaker[Session], *, ttl_seconds: int) -> None:
        self._factory = session_factory
        self._ttl = ttl_seconds

    def begin(self, scope: str, key: str, request_hash: str) -> StoredResponse | None:
        """Claim the key. Returns a stored response to replay, or None to execute."""
        with self._factory() as session:
            record = IdempotencyRecord(
                scope=scope,
                idem_key=key,
                request_hash=request_hash,
                status=_IN_PROGRESS,
                expires_at=now() + timedelta(seconds=self._ttl),
            )
            session.add(record)
            try:
                session.commit()
                return None
            except IntegrityError:
                session.rollback()
            existing = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == key,
                )
            )
            if existing is None:
                # The competing row was purged between insert and select; retry once.
                session.add(record)
                session.commit()
                return None
            if existing.expires_at <= now():
                session.execute(
                    delete(IdempotencyRecord).where(IdempotencyRecord.id == existing.id)
                )
                session.commit()
                session.add(record)
                session.commit()
                return None
            if existing.request_hash != request_hash:
                raise ConflictError("相同 Idempotency-Key 已用于不同的请求内容")
            if existing.status == _COMPLETED:
                return StoredResponse(
                    status_code=existing.response_status or 200,
                    body=existing.response_body,
                )
            raise ConflictError("相同 Idempotency-Key 的请求正在处理中")

    def complete(self, scope: str, key: str, status_code: int, body: Any) -> None:
        with self._factory() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == key,
                    IdempotencyRecord.status == _IN_PROGRESS,
                )
            )
            if record is None:
                return
            record.status = _COMPLETED
            record.response_status = status_code
            record.response_body = body
            session.commit()

    def abort(self, scope: str, key: str) -> None:
        """Drop the claim so the client can retry after a failed request."""
        with self._factory() as session:
            session.execute(
                delete(IdempotencyRecord).where(
                    IdempotencyRecord.scope == scope,
                    IdempotencyRecord.idem_key == key,
                    IdempotencyRecord.status == _IN_PROGRESS,
                )
            )
            session.commit()

    def purge_expired(self, limit: int = 1000) -> int:
        with self._factory() as session:
            ids = session.scalars(
                select(IdempotencyRecord.id)
                .where(IdempotencyRecord.expires_at <= now())
                .limit(limit)
            ).all()
            if not ids:
                return 0
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.id.in_(ids)))
            session.commit()
            return len(ids)


_default_store: IdempotencyStore | None = None


def _get_store() -> IdempotencyStore:
    global _default_store
    if _default_store is None:
        _default_store = IdempotencyStore(
            get_session_factory(),
            ttl_seconds=settings.IDEMPOTENCY_TTL_SECONDS,
        )
    return _default_store


def idempotent(
    *,
    required: bool = False,
    status_code: int = 200,
    store_factory: Callable[[], IdempotencyStore] | None = None,
) -> Callable[[F], F]:
    """Guard a write endpoint. `required=True` rejects requests without the header.

    Set ``status_code`` to the endpoint's declared status for plain return values;
    explicit Response objects retain their own status and body when replayed.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = _find_request(args, kwargs)
            key = (request.headers.get("Idempotency-Key") or "").strip()
            if not key:
                if required:
                    raise BadRequestError("缺少 Idempotency-Key 请求头")
                return await _invoke(func, args, kwargs)
            if len(key) > _MAX_KEY_LENGTH:
                raise BadRequestError(f"Idempotency-Key 不能超过 {_MAX_KEY_LENGTH} 个字符")

            scope = _scope(request)
            request_hash = hashlib.sha256(await request.body()).hexdigest()
            store = store_factory() if store_factory is not None else _get_store()
            replay = await run_in_threadpool(store.begin, scope, key, request_hash)
            if replay is not None:
                logger.info(
                    f"[{getattr(request.state, 'request_id', '-')}] 幂等重放 "
                    f"{request.method} {request.url.path} key_hash={_key_fingerprint(key)}"
                )
                return _replay_response(replay)

            try:
                result = await _invoke(func, args, kwargs)
            except BaseException:
                await run_in_threadpool(store.abort, scope, key)
                raise

            response_status = result.status_code if isinstance(result, Response) else status_code
            body = _pack_response(result)
            await run_in_threadpool(store.complete, scope, key, response_status, body)
            return result

        return wrapper  # type: ignore[return-value]

    return decorator


_RESPONSE_MARKER = "__idempotency_response_v1__"
_VOLATILE_RESPONSE_HEADERS = frozenset({b"content-length", b"date", b"x-request-id"})


def _pack_response(result: Any) -> dict[str, Any]:
    if isinstance(result, Response):
        body = getattr(result, "body", b"")
        if body is None:
            body = b""
        headers = [
            [name.decode("latin-1"), value.decode("latin-1")]
            for name, value in result.raw_headers
            if name.lower() not in _VOLATILE_RESPONSE_HEADERS
        ]
        return {
            _RESPONSE_MARKER: "raw",
            "body": base64.b64encode(body).decode("ascii"),
            "headers": headers,
        }
    return {_RESPONSE_MARKER: "json", "body": jsonable_encoder(result)}


def _replay_response(replay: StoredResponse) -> Response:
    stored = replay.body
    if isinstance(stored, dict) and stored.get(_RESPONSE_MARKER) == "raw":
        body = base64.b64decode(stored.get("body", ""), validate=True)
        headers = stored.get("headers", [])
        response = Response(content=body, status_code=replay.status_code)
        response.raw_headers = [
            (str(name).encode("latin-1"), str(value).encode("latin-1"))
            for name, value in headers
            if isinstance(name, str) and isinstance(value, str)
        ]
        if not any(name.lower() == b"content-length" for name, _ in response.raw_headers):
            response.raw_headers.append((b"content-length", str(len(body)).encode("ascii")))
        return response
    if isinstance(stored, dict) and stored.get(_RESPONSE_MARKER) == "json":
        stored = stored.get("body")
    return JSONResponse(content=stored, status_code=replay.status_code)


def _key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _find_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> Request:
    request = kwargs.get("request")
    if isinstance(request, Request):
        return request
    for arg in args:
        if isinstance(arg, Request):
            return arg
    raise RuntimeError("使用 @idempotent 的端点必须声明 request: Request 参数")


async def _invoke(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return await run_in_threadpool(func, *args, **kwargs)


def _scope(request: Request) -> str:
    user_id = request.headers.get("X-User-Id", "-")
    app_id = request.headers.get("X-App-Id", "-")
    return f"{app_id}:{user_id}:{request.method}:{request.url.path}"


async def cleanup_forever(stop: asyncio.Event) -> None:
    """Periodically purge expired rows; sleeps first so tests never touch the DB."""
    interval = settings.IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS
    if interval <= 0:
        return
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            removed = await run_in_threadpool(_get_store().purge_expired)
            if removed:
                logger.info(f"清理过期幂等记录 {removed} 条")
        except Exception:
            logger.exception("清理过期幂等记录失败")
