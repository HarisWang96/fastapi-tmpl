"""health router"""

from fastapi import APIRouter
from datetime import datetime

from app.utils.response import success_response
from app.schemas.response import ResponseModel

router = APIRouter(tags=["health"])


@router.get("/health", response_model=ResponseModel)
async def health_check():
    """health check endpoint"""
    data = {"status": "healthy", "timestamp": datetime.now().isoformat()}
    return success_response(data=data)
