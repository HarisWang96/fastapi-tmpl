"""Task API routes"""

from fastapi import APIRouter
from celery.result import AsyncResult

from app.celery_app import celery_app
from app.tasks import example_task

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/example")
async def create_example_task(data: dict = None):
    """
    Create an example background task.

    Args:
        data: Optional data to process

    Returns:
        Task ID for tracking
    """
    if data is None:
        data = {"message": "Hello from background task"}

    task = example_task.delay(data)
    return {
        "task_id": task.id,
        "status": "queued",
    }


@router.get("/status/{task_id}")
async def get_task_status(task_id: str):
    """
    Get the status of a background task.

    Args:
        task_id: The task ID returned when creating the task

    Returns:
        Task status and result if completed
    """
    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.ready():
        response["result"] = result.get()
    elif result.failed():
        response["error"] = str(result.result)

    return response
