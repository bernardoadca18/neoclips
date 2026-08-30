"""NeoClips Celery tasks (placeholder for future stages)."""

from app.core.celery_app import celery_app


@celery_app.task(name="app.tasks.placeholder")
def placeholder_task() -> str:
    """Placeholder task for testing Celery setup."""
    return "ok"
