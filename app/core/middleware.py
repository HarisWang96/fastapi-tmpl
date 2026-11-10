"""Request context middleware for request IDs and access logs.

This uses pure ASGI rather than BaseHTTPMiddleware to avoid interfering with
streaming responses (SSE) and background tasks. Headers can only be changed at
http.response.start, so the request ID is returned in a header and duration is logged.

Kubernetes probes are not logged at INFO level. Set LOG_LEVEL=DEBUG when investigating them.
"""

import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import metrics
from app.core.context import request_id_ctx
from app.core.logger import logger

# Keep these probe paths in sync with app/api/routes/health.py.
_PROBE_PATHS = frozenset({"/livez", "/readyz", "/healthz"})
_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        supplied_request_id = _get_header(scope, b"x-request-id")
        request_id = (
            supplied_request_id
            if supplied_request_id and _REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else uuid.uuid4().hex
        )
        scope.setdefault("state", {})["request_id"] = request_id
        context_token = request_id_ctx.set(request_id)
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(context_token)
            elapsed = time.perf_counter() - started
            path = scope.get("path")
            route = scope.get("route")
            metrics.observe_http(
                method=str(scope.get("method")),
                path=getattr(route, "path", None) or "unmatched",
                status=status_code,
                seconds=elapsed,
            )
            if path in _PROBE_PATHS:
                logger.debug(f"[{request_id}] {scope.get('method')} {path} status={status_code}")
            else:
                logger.info(
                    f"[{request_id}] {scope.get('method')} {path} "
                    f"status={status_code} elapsed={elapsed * 1000:.1f}ms"
                )


def _get_header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None
