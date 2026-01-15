"""Celery application configuration module"""

from celery import Celery

from app.config import settings

# Create Celery application instance
celery_app = Celery(
    "worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks"],  # Include task modules
)

# Celery configuration
celery_app.conf.update(
    # Task serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # Timezone
    timezone="UTC",
    enable_utc=True,
    # Task execution settings
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    # Result expiration
    result_expires=3600,  # 1 hour
    # Worker settings
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
    # RedBeat configuration (distributed beat scheduler)
    # Prevents duplicate task scheduling in multi-pod K8s deployments
    redbeat_redis_url=settings.REDIS_URL,
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_lock_timeout=30,  # Lock timeout in seconds
)

# Beat schedule for periodic tasks
# Using RedBeat ensures only one instance schedules tasks across all pods
celery_app.conf.beat_schedule = {
    # Example: Run every minute
    # "example-periodic-task": {
    #     "task": "app.tasks.example.example_periodic_task",
    #     "schedule": 60.0,  # seconds
    # },
}
