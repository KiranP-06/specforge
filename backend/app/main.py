"""SPECForge API entrypoint."""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text

from . import metrics
from .config import get_settings
from .db import SessionLocal, init_db
from .routers import auth, items, projects

settings = get_settings()
logging.basicConfig(level=logging.INFO, format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("specforge.api")

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.auto_create_tables:
        init_db()  # dev/tests; production runs `alembic upgrade head` before the API starts
    metrics.register_collectors()
    log.info("SPECForge %s (%s) started, llm_provider=%s", settings.version, settings.git_sha, settings.llm_provider)
    yield


app = FastAPI(
    lifespan=lifespan,
    title="SPECForge API",
    version=settings.version,
    description="Turn a project brief into a connected, self-checking software blueprint and track its delivery.",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def access_log(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t0
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")  # template, e.g. /api/items/{item_id} — keeps label cardinality low
    if route_path != "/metrics":
        metrics.observe_request(request.method, route_path, response.status_code, elapsed)
    if request.url.path not in ("/health", "/metrics"):
        log.info("%s %s %s %.1fms", request.method, request.url.path, response.status_code, elapsed * 1000)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.get("/health", tags=["ops"])
def health():
    """Liveness probe: process is up."""
    return {"status": "ok", "version": settings.version, "git_sha": settings.git_sha}


@app.get("/ready", tags=["ops"])
def ready():
    """Readiness probe: database (and Redis when Celery is used) reachable."""
    checks = {}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {exc.__class__.__name__}"
    if not settings.inline_jobs:
        try:
            import redis

            redis.Redis.from_url(settings.redis_url, socket_timeout=2).ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc.__class__.__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@app.get("/metrics", tags=["ops"], include_in_schema=False)
def prometheus_metrics():
    """Prometheus scrape endpoint (not routed through the public ingress)."""
    body, content_type = metrics.render()
    return Response(body, media_type=content_type)


@app.get("/api/meta", tags=["ops"])
def meta():
    from .services import heuristic, nlp

    return {"app": settings.app_name, "version": settings.version, "environment": settings.environment,
            "llm_provider": settings.llm_provider, "ml_backend": "transformers" if nlp.using_transformers() else "lightweight",
            "nlp_parser": "spacy" if heuristic.using_spacy() else "regex"}


app.include_router(auth.router)
app.include_router(auth.users_router)
app.include_router(projects.router)
app.include_router(items.router)
