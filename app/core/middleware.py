"""Pure ASGI request ID, structured access logging, and latency metrics."""

import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.context import request_id_ctx, trace_id_ctx
from app.core.metrics import observe_http
from app.logger import logger

_REQUEST_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_PROBES = {"/livez", "/readyz", "/healthz"}


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        supplied = next(
            (
                v.decode("latin-1")
                for k, v in scope.get("headers", [])
                if k == b"x-request-id"
            ),
            None,
        )
        request_id = (
            supplied
            if supplied and _REQUEST_ID.fullmatch(supplied)
            else uuid.uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_ctx.set(request_id)
        trace_token = trace_id_ctx.set(_traceparent(scope))
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-Id"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_ctx.reset(token)
            trace_id_ctx.reset(trace_token)
            elapsed = time.perf_counter() - started
            path = scope.get("path", "")
            route = scope.get("route")
            observe_http(
                str(scope.get("method", "")),
                getattr(route, "path", None) or "unmatched",
                status,
                elapsed,
            )
            message = (
                "request_id={} method={} path={} status={} elapsed_ms={:.1f}".format(
                    request_id, scope.get("method"), path, status, elapsed * 1000
                )
            )
            (logger.debug if path in _PROBES else logger.info)(message)


def _traceparent(scope: Scope) -> str | None:
    """Return the W3C trace ID from a syntactically valid traceparent."""
    value = next(
        (v.decode("latin-1") for k, v in scope.get("headers", []) if k == b"traceparent"),
        None,
    )
    if value is None:
        return None
    parts = value.split("-")
    if len(parts) != 4 or len(parts[1]) != 32 or parts[1] == "0" * 32:
        return None
    try:
        int(parts[0], 16)
        int(parts[1], 16)
        int(parts[2], 16)
        int(parts[3], 16)
    except ValueError:
        return None
    return parts[1]
