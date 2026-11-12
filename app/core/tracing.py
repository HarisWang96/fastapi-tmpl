"""Optional OpenTelemetry setup for inbound and HTTPX client spans."""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.config import settings

_provider: TracerProvider | None = None


def configure_tracing() -> None:
    """Install a process-wide provider when tracing is enabled."""
    global _provider
    if not settings.OTEL_ENABLED or _provider is not None:
        return
    _provider = TracerProvider(
        resource=Resource.create(
            {"service.name": settings.APP_NAME, "service.version": settings.APP_VERSION}
        )
    )
    exporter_options = {}
    if settings.OTEL_EXPORTER_OTLP_ENDPOINT:
        exporter_options["endpoint"] = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    if settings.OTEL_EXPORTER_OTLP_HEADERS:
        exporter_options["headers"] = dict(
            pair.split("=", 1)
            for pair in settings.OTEL_EXPORTER_OTLP_HEADERS.split(",")
            if "=" in pair
        )
    _provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(**exporter_options))
    )
    trace.set_tracer_provider(_provider)
    HTTPXClientInstrumentor().instrument()


def instrument_app(app) -> None:
    if settings.OTEL_ENABLED:
        configure_tracing()
        FastAPIInstrumentor.instrument_app(app)


def shutdown_tracing() -> None:
    global _provider
    if _provider is None:
        return
    HTTPXClientInstrumentor().uninstrument()
    _provider.shutdown()
    _provider = None
