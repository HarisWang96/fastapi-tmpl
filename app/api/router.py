"""Route aggregation: main.py includes only this router.

Keep registration order stable (probes, then business routes).
Probes are unprefixed; business endpoints use API_PREFIX.

For a new domain, define an APIRouter in app/modules/<domain>/api.py and mount
it here with the service-wide prefix.
"""

from fastapi import APIRouter

from app.api.routes import demo, health
from app.core.config import settings
from app.modules._example.api import router as example_routes


def build_api_router() -> APIRouter:
    """Rebuild routes for each app so settings are read at app creation time."""
    router = APIRouter()

    # Probes are unprefixed because Kubernetes health checks have no caller identity.
    router.include_router(health.router)

    business = APIRouter()
    business.include_router(example_routes)
    # Demo endpoints are for local development and are hidden in production.
    if settings.APP_ENV != "prod":
        business.include_router(demo.router)
    router.include_router(business, prefix=settings.API_PREFIX)
    return router
