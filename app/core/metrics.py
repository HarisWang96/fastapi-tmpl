"""Prometheus HTTP metrics with bounded route labels."""

import hmac

from fastapi import Request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.responses import Response

from app.config import settings

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests", ["service", "method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration",
    ["service", "method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)


def observe_http(method: str, path: str, status: int, seconds: float) -> None:
    if path == "/metrics":
        return
    HTTP_REQUESTS.labels(settings.APP_NAME, method, path, str(status)).inc()
    HTTP_LATENCY.labels(settings.APP_NAME, method, path).observe(seconds)


def render(request: Request) -> Response:
    expected = settings.METRICS_TOKEN
    token = request.headers.get("x-metrics-token")
    auth = request.headers.get("authorization", "")
    if not token and auth.lower().startswith("bearer "):
        token = auth[7:]
    if expected and (
        not token or not hmac.compare_digest(token, expected.get_secret_value())
    ):
        return Response("forbidden", status_code=403)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
