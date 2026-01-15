"""Celery tasks module"""

from app.tasks.example import example_task, example_periodic_task

__all__ = ["example_task", "example_periodic_task"]

