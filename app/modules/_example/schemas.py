"""Request and response models for the example domain."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.schemas.common import ORMModel


class CreateUserRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64, description="用户姓名")
    mobile: str | None = Field(default=None, max_length=20, description="手机号")


class UserItem(ORMModel):
    id: int
    user_name: str
    user_mobile: str
    create_time: datetime | None = None
    update_time: datetime | None = None


class UserPage(BaseModel):
    list: list[UserItem]
    total: int
    page: int
    page_size: int
