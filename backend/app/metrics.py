"""Prometheus metrics.

Two kinds:
* request metrics recorded by middleware (rate, latency, status) per route template;
* business metrics computed at scrape time from the database and Redis (jobs, quality
  scores, stale items, findings, queue backlog). Computing them at scrape time means the
  API pods report what the Celery worker did without needing a push gateway.
"""
from __future__ import annotations

import logging
import time

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, Info, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select

from .config import get_settings

log = logging.getLogger("specforge.metrics")

HTTP_REQUESTS = Counter("specforge_http_requests_total", "HTTP requests", ["method", "route", "status"])
HTTP_LATENCY = Histogram(
    "specforge_http_request_duration_seconds", "HTTP request latency", ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
)
EXPORTS = Counter("specforge_exports_total", "Blueprint exports", ["format"])
LOGINS = Counter("specforge_logins_total", "Login attempts", ["result"])
BUILD = Info("specforge_build", "Running build (shows which commit CD deployed)")


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_LATENCY.labels(method, route).observe(seconds)


class BusinessCollector:
    """Reads current state from PostgreSQL / Redis on every scrape."""

    def collect(self):
        from .db import SessionLocal
        from .models import Finding, Item, Job, Project

        jobs = GaugeMetricFamily("specforge_jobs", "Generation/check jobs by kind and status", labels=["kind", "status"])
        job_secs = GaugeMetricFamily("specforge_job_last_duration_seconds", "Duration of the most recent successful job", labels=["kind"])
        projects = GaugeMetricFamily("specforge_projects", "Number of projects")
        quality = GaugeMetricFamily("specforge_blueprint_quality_score", "Blueprint Quality Score per project", labels=["project_id", "project"])
        items = GaugeMetricFamily("specforge_blueprint_items", "Blueprint items by type", labels=["type"])
        stale = GaugeMetricFamily("specforge_stale_items", "Items flagged by change impact and not yet reviewed")
        findings = GaugeMetricFamily("specforge_findings", "Open consistency findings by severity", labels=["severity"])
        up = GaugeMetricFamily("specforge_database_up", "1 if the database answered the metrics query")
        try:
            with SessionLocal() as db:
                for kind, status, n in db.execute(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)):
                    jobs.add_metric([kind, status], n)
                for kind in ("generate", "check"):
                    last = db.scalars(select(Job).where(Job.kind == kind, Job.status == "succeeded").order_by(Job.id.desc()).limit(1)).first()
                    if last and last.result and "seconds" in last.result:
                        job_secs.add_metric([kind], float(last.result["seconds"]))
                projects.add_metric([], db.scalar(select(func.count()).select_from(Project)) or 0)
                for pid, name, score in db.execute(select(Project.id, Project.name, Project.quality_score).where(Project.quality_score.isnot(None))):
                    quality.add_metric([str(pid), name[:60]], float(score))
                for type_, n in db.execute(select(Item.type, func.count()).group_by(Item.type)):
                    items.add_metric([type_], n)
                stale.add_metric([], db.scalar(select(func.count()).select_from(Item).where(Item.stale.is_(True))) or 0)
                for sev, n in db.execute(select(Finding.severity, func.count()).group_by(Finding.severity)):
                    findings.add_metric([sev], n)
            up.add_metric([], 1)
        except Exception as exc:  # noqa: BLE001 - a scrape must never crash
            log.warning("metrics collection failed: %s", exc)
            up.add_metric([], 0)
        yield from (jobs, job_secs, projects, quality, items, stale, findings, up)

        s = get_settings()
        if not s.inline_jobs:
            backlog = GaugeMetricFamily("specforge_queue_backlog", "Celery jobs waiting in Redis")
            try:
                import redis

                backlog.add_metric([], redis.Redis.from_url(s.redis_url, socket_timeout=2).llen("celery"))
                yield backlog
            except Exception as exc:  # noqa: BLE001
                log.warning("queue backlog unavailable: %s", exc)


_registered = False


def register_collectors() -> None:
    global _registered
    if not _registered:
        s = get_settings()
        BUILD.info({"version": s.version, "git_sha": s.git_sha[:12], "environment": s.environment, "llm_provider": s.llm_provider})
        REGISTRY.register(BusinessCollector())
        _registered = True


def render() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


class Timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t0
