"""Framework smoke-test endpoints for response contracts and identity dependencies."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import CallerDep, RequiredCallerDep
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
