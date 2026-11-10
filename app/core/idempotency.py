"""Async PostgreSQL-backed Idempotency-Key support."""

import asyncio
import base64
import functools
import hashlib
import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from fastapi import Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.database import AsyncSessionLocal
from app.errors import AppError
from app.logger import logger
from app.models.platform import IdempotencyRecord

_IN_PROGRESS, _COMPLETED = 1, 2
_MARKER = "__idempotency_response_v1__"
_VOLATILE_HEADERS = {"content-length", "date", "x-request-id"}
F = TypeVar("F", bound=Callable[..., Any])


class IdempotencyError(AppError):
    def __init__(self, message: str, status_code: int = 409, code: int = 1409) -> None:
        super().__init__(message, status_code=status_code, code=code)


def _now() -> datetime:
    return datetime.now(UTC)


def _scope(request: Request) -> str:
    app_id = request.headers.get("X-App-Id", "-")
    user_id = request.headers.get("X-User-Id", "-")
    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    return f"{app_id}:{user_id}:{request.method}:{path}"


def _pack(result: Any) -> tuple[int, Any, dict[str, str]]:
    if isinstance(result, Response):
        body = getattr(result, "body", b"") or b""
        packed = {_MARKER: "raw", "body": base64.b64encode(body).decode("ascii")}
        headers = {
            k.decode("latin-1"): v.decode("latin-1")
            for k, v in result.raw_headers
            if k.decode("latin-1").lower() not in _VOLATILE_HEADERS
        }
        return result.status_code, packed, headers
    return 200, {_MARKER: "json", "body": jsonable_encoder(result)}, {}


def _replay(record: IdempotencyRecord) -> Response:
    body = record.response_body
    headers = record.response_headers or {}
    if isinstance(body, dict) and body.get(_MARKER) == "raw":
        raw = base64.b64decode(body["body"], validate=True)
        return Response(raw, status_code=record.response_status or 200, headers=headers)
    if isinstance(body, dict) and body.get(_MARKER) == "json":
        body = body.get("body")
    return JSONResponse(
        body, status_code=record.response_status or 200, headers=headers
    )


async def _claim(scope: str, key: str, digest: str) -> IdempotencyRecord | None:
    async with AsyncSessionLocal() as session:
        record = IdempotencyRecord(
            scope=scope,
            idem_key=key,
            request_hash=digest,
            status=_IN_PROGRESS,
            created_at=_now(),
            expires_at=_now() + timedelta(seconds=settings.IDEMPOTENCY_TTL_SECONDS),
        )
        session.add(record)
        try:
            await session.commit()
            return None
        except IntegrityError:
            await session.rollback()
        existing = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.idem_key == key
            )
        )
        if existing is None:
            raise IdempotencyError("Could not claim idempotency key")
        if existing.expires_at <= _now():
            await session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.id == existing.id)
            )
            await session.commit()
            return await _claim(scope, key, digest)
        if existing.request_hash != digest:
            raise IdempotencyError(
                "Idempotency-Key was already used with a different request", 409, 1409
            )
        if existing.status != _COMPLETED:
            raise IdempotencyError(
                "Request with this Idempotency-Key is still in progress", 409, 1409
            )
        return existing


async def _complete(
    scope: str, key: str, status: int, body: Any, headers: dict[str, str]
) -> None:
    async with AsyncSessionLocal() as session:
        record = await session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope, IdempotencyRecord.idem_key == key
            )
        )
        if record is not None:
            record.status = _COMPLETED
            record.response_status = status
            record.response_body = body
            record.response_headers = headers
            await session.commit()


async def _abort(scope: str, key: str) -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idem_key == key,
                IdempotencyRecord.status == _IN_PROGRESS,
            )
        )
        await session.commit()


def idempotent(*, required: bool = False, status_code: int = 200) -> Callable[[F], F]:
    """Wrap an endpoint. For plain values, pass the route's non-200 status_code."""

    def decorate(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            request = kwargs.get("request") or next(
                (arg for arg in args if isinstance(arg, Request)), None
            )
            if request is None:
                raise RuntimeError("idempotent endpoint must declare request: Request")
            key = (request.headers.get("Idempotency-Key") or "").strip()
            if not key:
                if required:
                    raise IdempotencyError("Missing Idempotency-Key", 400, 1400)
                return await _invoke(func, args, kwargs)
            if len(key) > 128:
                raise IdempotencyError(
                    "Idempotency-Key exceeds 128 characters", 400, 1400
                )
            scope = _scope(request)
            digest = hashlib.sha256(await request.body()).hexdigest()
            existing = await _claim(scope, key, digest)
            fingerprint = hashlib.sha256(key.encode()).hexdigest()[:12]
            if existing is not None:
                logger.info(
                    "idempotency replay method={} path={} key_hash={}",
                    request.method,
                    request.url.path,
                    fingerprint,
                )
                return _replay(existing)
            try:
                result = await _invoke(func, args, kwargs)
                status, body, headers = _pack(result)
                if not isinstance(result, Response):
                    status = status_code
                await _complete(scope, key, status, body, headers)
                return result
            except BaseException:
                await _abort(scope, key)
                raise

        return wrapper  # type: ignore[return-value]

    return decorate


async def _invoke(
    func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]
) -> Any:
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return await run_in_threadpool(func, *args, **kwargs)


async def cleanup_forever(stop: asyncio.Event) -> None:
    interval = settings.IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS
    if interval <= 0:
        return
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    delete(IdempotencyRecord).where(
                        IdempotencyRecord.expires_at <= _now()
                    )
                )
                await session.commit()
                if result.rowcount:
                    logger.info(
                        "purged expired idempotency records count={}", result.rowcount
                    )
