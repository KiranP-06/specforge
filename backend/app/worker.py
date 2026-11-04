"""Celery worker: heavy NLP / LLM work runs here so the API stays responsive.

Run with:  celery -A app.worker.celery_app worker --loglevel=INFO
"""
from celery import Celery

from .config import get_settings

settings = get_settings()
celery_app = Celery("specforge", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=900,
    broker_connection_retry_on_startup=True,
)


@celery_app.task(name="specforge.generate")
def generate_task(job_id: int) -> None:
    from .services.pipeline import run_generation

    run_generation(job_id)


@celery_app.task(name="specforge.check")
def check_task(job_id: int) -> None:
    from .services.pipeline import run_check

    run_check(job_id)


def dispatch(kind: str, job_id: int, background=None) -> None:
    """Send a job to Celery, or run it in-process when INLINE_JOBS=true."""
    from .services.pipeline import run_check, run_generation

    fn = {"generate": run_generation, "check": run_check}[kind]
    if settings.inline_jobs:
        if background is not None:
            background.add_task(fn, job_id)
        else:
            fn(job_id)
    else:
        {"generate": generate_task, "check": check_task}[kind].delay(job_id)
