"""Celery application configuration for NeoClips."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "neoclips",
    broker=str(settings.redis_url),
    backend=str(settings.redis_url),
    include=["app.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Worker settings - conservative for single workstation
    worker_prefetch_multiplier=settings.celery_worker_prefetch_multiplier,
    worker_concurrency=settings.celery_worker_concurrency,
    task_acks_late=True,

    # Connection settings
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=5,

    # Result backend settings
    result_expires=86400,  # 24 hours

    # Task routing
    task_routes={
        "app.tasks.*": {"queue": settings.celery_queue_name},
    },

    # Default queue
    task_default_queue=settings.celery_queue_name,

    # Disable task result backend for MVP (using PostgreSQL as source of truth)
    task_ignore_result=True,
)


def get_celery_app() -> Celery:
    """Get the Celery application instance."""
    return celery_app
