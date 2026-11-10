"""Framework smoke-test endpoints for response contracts and identity dependencies."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.authz_deps import require_perm, require_scope
from app.api.deps import Caller, CallerDep, RequiredCallerDep
from app.clients.authz import DataScope
from app.core.schemas.common import ApiResponse, success

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/ping", response_model=ApiResponse[dict[str, Any]])
def ping() -> ApiResponse[Any]:
    return success({"pong": True})


@router.get("/echo", response_model=ApiResponse[dict[str, Any]])
def echo(message: Annotated[str, Query(min_length=1, max_length=20)]) -> ApiResponse[Any]:
    """Demonstrate validation errors using the standard response envelope."""
    return success({"message": message})


@router.get("/whoami", response_model=ApiResponse[dict[str, Any]])
def whoami(caller: CallerDep) -> ApiResponse[Any]:
    """Public endpoint: missing identity headers result in null identity fields."""
    return success({"user_id": caller.user_id, "app_id": caller.app_id})


@router.get("/me", response_model=ApiResponse[dict[str, Any]])
def me(caller: RequiredCallerDep) -> ApiResponse[Any]:
    """Require identity and return 401 when X-User-Id is missing."""
    return success({"user_id": caller.user_id, "app_id": caller.app_id})


@router.get("/perm", response_model=ApiResponse[dict[str, Any]])
async def perm(
    caller: Annotated[Caller, Depends(require_perm("demo:read"))],
) -> ApiResponse[Any]:
    """Service-side permission check; 403 when authz-svc denies the code."""
    return success({"user_id": caller.user_id, "perm": "demo:read"})


@router.get("/scope", response_model=ApiResponse[dict[str, Any]])
async def scoped(
    scope: Annotated[DataScope, Depends(require_scope("demo", "dept"))],
) -> ApiResponse[Any]:
    """Data scope for the caller; filter_values() is None for ALL, [] for NONE."""
    return success(
        {
            "mode": scope.mode,
            "dimension": scope.dimension,
            "values": scope.values,
            "filter_values": scope.filter_values(),
        }
    )
