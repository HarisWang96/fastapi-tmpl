"""A small route used to verify the API layer and request validation."""

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field

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
