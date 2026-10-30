"""Example domain endpoints.

Use this structure for new domains: one APIRouter per resource group, with its
prefix declared here and mounted centrally by app/api/router.py.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import DbSession, RequiredCallerDep
from app.core.logger import logger
from app.core.schemas.common import ApiResponse, success
from app.modules._example import service
from app.modules._example.schemas import CreateUserRequest, UserPage

router = APIRouter(prefix="/example", tags=["example"])


@router.get("/users", response_model=ApiResponse[UserPage])
def list_users(
    db: DbSession,
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 20,
    search: Annotated[str | None, Query(max_length=50, description="姓名/手机号模糊搜索")] = None,
) -> ApiResponse[Any]:
    return success(service.list_users(db, keyword=search, page=page, page_size=page_size))


@router.post("/users", response_model=ApiResponse[dict[str, int]])
def create_user(
    body: CreateUserRequest,
    caller: RequiredCallerDep,
    db: DbSession,
) -> ApiResponse[Any]:
    new_id = service.create_user(db, name=body.name, mobile=body.mobile)
    # The dependency commit runs after the response, so commit here before returning 200.
    db.commit()
    logger.info(f"用户 {caller.user_id} 新增 demo 用户 id={new_id}")
    return success({"id": new_id}, message="新增成功")
