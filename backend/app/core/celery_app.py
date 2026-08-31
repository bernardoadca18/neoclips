"""Celery application configuration for NeoClips."""

import logging

from celery import Celery
from celery.signals import worker_ready

from app.core.config import get_settings

logger = logging.getLogger(__name__)

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


@worker_ready.connect  # type: ignore[untyped-decorator]
def on_worker_ready(**kwargs: object) -> None:
    """
    Resume incomplete sources at worker startup.

    This recovers from worker crashes by restarting polling tasks
    for sources stuck in non-terminal states (ingesting, transcribing).
    """
    from app.tasks import resume_incomplete_sources

    logger.info("worker_startup_recovery_started")
    try:
        resumed_count = resume_incomplete_sources()
        logger.info("worker_startup_recovery_complete", extra={"resumed_count": resumed_count})
    except Exception as e:
        logger.error("worker_startup_recovery_failed", extra={"error": str(e)})


def get_celery_app() -> Celery:
    """Get the Celery application instance."""
    return celery_app
