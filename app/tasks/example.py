"""Example Celery tasks"""

import time
from celery import shared_task

from app.celery_app import celery_app


@celery_app.task(bind=True, max_retries=3)
def example_task(self, data: dict) -> dict:
    """
    Example background task.
    
    Args:
        data: Task input data
        
    Returns:
        Task result
    """
    try:
        # Simulate some work
        time.sleep(2)
        
        result = {
            "status": "success",
            "message": f"Processed data: {data}",
            "task_id": self.request.id,
        }
        return result
    except Exception as exc:
        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)


@shared_task
def example_periodic_task() -> dict:
    """
    Example periodic task.
    This task can be scheduled to run at regular intervals.
    
    Returns:
        Task result
    """
    return {
        "status": "success",
        "message": "Periodic task executed",
    }

