"""The end-to-end generation job: brief → draft → graph → self-check → quality score."""
from __future__ import annotations

import logging
import time

from ..db import SessionLocal
from ..models import Job, Project
from . import checker, graph
from .generator import generate_blueprint

log = logging.getLogger("specforge.pipeline")


def _stage(db, job: Job, stage: str, progress: int) -> None:
    job.stage, job.progress = stage, progress
    db.commit()


def run_generation(job_id: int) -> None:
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return
    project = db.get(Project, job.project_id)
    t0 = time.perf_counter()
    try:
        job.status = "running"
        project.status = "generating"
        _stage(db, job, "Understanding brief", 10)
        if not project.brief_text.strip():
            raise ValueError("Project has no brief. Upload or paste one first.")
        result = generate_blueprint(project.brief_text)
        _stage(db, job, "Building blueprint graph", 50)
        graph.clear_blueprint(db, project.id)
        graph.persist_draft(db, project, result.draft)
        db.commit()
        _stage(db, job, "Self-checking & repairing", 75)
        quality = checker.self_check(db, project)
        project.status = "draft"
        job.status, job.progress, job.stage = "succeeded", 100, "Done"
        job.result = {
            "provider": result.provider, "attempts": result.attempts, "fallback_used": result.fallback,
            "validation_errors": result.errors[:5], "quality": quality, "counts": graph.counts(db, project.id),
            "seconds": round(time.perf_counter() - t0, 2), "summary": result.draft.summary,
        }
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("generation job %s failed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        project = db.get(Project, job.project_id)
        job.status, job.error, job.stage = "failed", str(exc)[:2000], "Failed"
        project.status = "failed"
        db.commit()
    finally:
        db.close()


def run_check(job_id: int) -> None:
    db = SessionLocal()
    job = db.get(Job, job_id)
    try:
        job.status = "running"
        _stage(db, job, "Running consistency checks", 30)
        project = db.get(Project, job.project_id)
        quality = checker.self_check(db, project, repair=bool((job.result or {}).get("repair", True)))
        job.status, job.progress, job.stage, job.result = "succeeded", 100, "Done", {"quality": quality}
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        job = db.get(Job, job_id)
        job.status, job.error = "failed", str(exc)[:2000]
        db.commit()
    finally:
        db.close()
