"""enums router - example API for returning enum values"""

from fastapi import APIRouter

from app.utils.response import success_response
from app.schemas.response import ResponseModel

router = APIRouter(prefix="/enums", tags=["enums"])


@router.get("/status", response_model=ResponseModel)
async def get_status_enums():
    """get status enums example"""
    from app.enums.common import ORMStatusEnum

    data = [
        {"value": item.value, "label": item.name.replace("_", " ").title()}
        for item in ORMStatusEnum
    ]
    return success_response(data=data)


# Add your enum endpoints here
# Example:
# @router.get("/your-enum", response_model=ResponseModel)
# async def get_your_enums():
#     """get your enum values"""
#     from app.enums.common import YourBusinessEnum
#     data = [{"value": item.value, "label": item.name} for item in YourBusinessEnum]
#     return success_response(data=data)
