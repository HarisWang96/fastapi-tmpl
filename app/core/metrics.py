"""Prometheus metrics and the /metrics endpoint.

The path label always uses the matched route template instead of the raw URL:
otherwise /users/1 and /users/2 create separate time series and explode cardinality.

Business metrics (login results, decisions, ...) define their own Counter in the
owning module and appear on /metrics automatically; do not pile business labels here.
"""

import hmac

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from app.core.config import settings

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "HTTP 请求数",
    ["service", "method", "path", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP 处理耗时",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

_SKIP_PATHS = frozenset({"/metrics"})


def observe_http(*, method: str, path: str, status: int, seconds: float) -> None:
    if path in _SKIP_PATHS:
        return
    HTTP_REQUESTS.labels(settings.APP_NAME, method, path, str(status)).inc()
    HTTP_LATENCY.labels(settings.APP_NAME, method, path).observe(seconds)


def render(request: Request) -> Response:
    if not _authorized(_extract_token(request)):
        return Response("forbidden", status_code=403)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _authorized(token: str | None) -> bool:
    expected = settings.METRICS_TOKEN
    if expected is None:
        return True
    return bool(token) and hmac.compare_digest(token, expected.get_secret_value())


def _extract_token(request: Request) -> str | None:
    token = request.headers.get("x-metrics-token")
    if token:
        return token
    authorization = request.headers.get("authorization") or ""
    if authorization.lower().startswith("bearer "):
        return authorization[7:]
    return None
