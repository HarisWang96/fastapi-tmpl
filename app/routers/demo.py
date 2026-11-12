"""A small route used to verify the API layer and request validation."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path
from pydantic import BaseModel, Field

from app.clients.authz import DataScope
from app.dependencies import Caller, require_perm, require_scope

router = APIRouter(prefix="/api/v1/demo", tags=["demo"])


class GreetingRequest(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class GreetingResponse(BaseModel):
    message: str
    name: str


@router.get("/hello/{name}", response_model=GreetingResponse)
async def hello(name: str = Path(min_length=1, max_length=50)) -> GreetingResponse:
    return GreetingResponse(message=f"Hello, {name}", name=name)


@router.post("/greet", response_model=GreetingResponse)
async def greet(request: GreetingRequest) -> GreetingResponse:
    return GreetingResponse(message=f"Hello, {request.name}", name=request.name)


@router.get("/protected")
async def protected(
    caller: Annotated[Caller, Depends(require_perm("demo:read"))],
) -> dict[str, str | int]:
    """Example route demonstrating gateway identity and service authorization."""
    return {"user_id": caller.user_id or 0, "app_id": caller.app_id or ""}


@router.get("/protected-scope")
async def protected_scope(
    scope: Annotated[DataScope, Depends(require_scope("demo", "store"))],
) -> dict[str, object]:
    """Example of requesting a row/data scope from the authorization service."""
    return {
        "mode": scope.mode,
        "dimension": scope.dimension,
        "values": scope.values,
    }
