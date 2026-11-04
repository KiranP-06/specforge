# syntax=docker/dockerfile:1.7
# ---------- builder: compile wheels once ----------
FROM python:3.12-slim AS builder
ARG WITH_ML=false
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt requirements-ml.txt ./
RUN python -m venv /opt/venv && /opt/venv/bin/pip install -r requirements.txt \
 && if [ "$WITH_ML" = "true" ]; then \
      /opt/venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu && \
      /opt/venv/bin/pip install -r requirements-ml.txt ; fi

# ---------- runtime: small, non-root ----------
FROM python:3.12-slim AS runtime
ARG GIT_SHA=local
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GIT_SHA=$GIT_SHA \
    STORAGE_LOCAL_DIR=/app/data HF_HOME=/app/.cache UVICORN_WORKERS=1
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 specforge
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations
RUN mkdir -p /app/data /app/.cache /app/models && chown -R specforge:specforge /app
USER specforge
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://localhost:8000/health || exit 1
# One worker per container: scale with replicas so each pod's /metrics is complete.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS} --proxy-headers"]
