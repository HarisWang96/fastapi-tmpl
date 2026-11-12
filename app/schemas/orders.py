"""Request and response contracts for the example order service."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=100)
    quantity: int = Field(gt=0, le=1000)


class OrderView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    customer_id: str
    sku: str
    quantity: int
    status: str
    created_at: datetime
