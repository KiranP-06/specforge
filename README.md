# SPECForge

**Turn a project idea, brief, SOW or SRS into a complete, connected software blueprint — and track its delivery in one place.**

SPECForge generates requirements, user stories, modules, REST API suggestions, data entities, test scenarios and a risk register from a brief. It stores them as a linked graph rather than a document, checks the draft for gaps, duplicates and contradictions before anyone sees it, and flags every dependent item when a requirement changes.

> Independent DevOps + AI project · B.Tech CSE (AI & ML), SRM Institute of Science and Technology, Chennai

---

## What makes it different

| | |
|---|---|
| **Blueprint as a graph** | Every item is a node linked to the requirement it serves: `REQ → US → MOD → API → ENT`, `REQ → TC`, `REQ → RSK`. Coverage is measurable and the plan is queryable. |
| **Self-checking generation** | Drafts must validate against a strict JSON schema (invalid ones go back to the model for repair). A **rule layer** (coverage, orphans, vague wording, unmeasurable NFRs) and an **ML layer** (embedding duplicates, NLI contradictions, FR/NFR classifier) then run. Structural gaps are auto-repaired, and the result is summarised as a **Blueprint Quality Score**. |
| **Change-impact propagation** | Editing a requirement bumps its version and runs a graph traversal that flags every dependent story, API, entity, test and risk as *stale* until someone reviews it. |
| **Runs with no API key** | The default `heuristic` generator is fully offline and deterministic. You can switch to any OpenAI-compatible API (OpenAI, Groq, OpenRouter, Gemini, Ollama) or Anthropic with one environment variable. |

## Features

- Brief intake: paste text or upload **PDF / DOCX / TXT / MD**
- Generated blueprint: requirements (FR/NFR, category, MoSCoW priority, stakeholder), stories with Given/When/Then acceptance criteria, modules, entities with fields, REST endpoints, functional / negative / NFR tests, and a risk register (likelihood × impact)
- Traceability matrix (missing required links are highlighted) and an interactive graph view
- Team review: JWT auth with **RBAC** (admin / analyst / reviewer), approve or reject per item, comments, full version history
- **Baselines**: freeze the approved blueprint, then diff the current state against it
- Delivery dashboard: status per item, priority-weighted progress per requirement, top risks, findings by severity
- Semantic search over requirements (**pgvector**)
- Exports: **DOCX, PDF, CSV, JSON, Jira-import CSV, GitHub Issues** (`scripts/import_github_issues.sh`)
- NLP with **spaCy** dependency parsing (regex fallback), plus optional transformer models
- Async generation through **Celery + Redis**, so the UI stays responsive

## Architecture

```
Browser ──► Traefik Ingress (k3s) ──► web (Nginx + React SPA) ──► api (FastAPI, JWT/RBAC, OpenAPI)
                                                                   │            │
                                                     Redis (queue) ◄┘            ├─► PostgreSQL 16 + pgvector
                                                                   │            └─► Amazon S3 (uploads, exports, backups)
                                                     worker (Celery: NLP pipeline, LLM calls, self-check)
                                                                   └─► LLM provider (pluggable, optional)
All on one EC2 instance (k3s) · logs, metrics and alarms → CloudWatch
```

| Layer | Tech |
|---|---|
| Frontend | React 18, TypeScript, Vite, React Router · ESLint, Vitest |
| API | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, PyJWT, bcrypt |
| Engine | Schema-constrained generation + repair loop, rule engine, embeddings, NLI cross-encoder (optional, CPU), scikit-learn classifier |
| Data | PostgreSQL 16 + pgvector, Redis 7, Amazon S3 |
| Delivery | Docker (multi-stage, non-root), Docker Compose, Docker Swarm, Kubernetes (k3s) + Kustomize overlays, Alembic migrations, Terraform, Ansible, GitHub Actions, GHCR, Trivy, Bandit |
| Observability | Prometheus (app + node metrics, 7 alert rules), Grafana (provisioned dashboard), CloudWatch (logs, metrics, alarms, SNS) |

## Repository layout

```
backend/            FastAPI app, blueprint engine, tests (pytest), Dockerfile
frontend/           React + TS SPA, Nginx template, tests (vitest), Dockerfile
deploy/terraform/   VPC, security group, EC2 + EIP, S3, CloudWatch logs/alarms/dashboard, remote state
deploy/ansible/     Host hardening, Docker, k3s, CloudWatch agent, GitHub runner, app deploy
deploy/k8s/         base/ (app), monitoring/ (Prometheus, Grafana, node-exporter), overlays/aws + overlays/local
.github/workflows/  CI/CD: lint → test → SAST → scan → build → push → deploy → smoke test → rollback
scripts/            deploy.sh (CD + auto-rollback), smoke_test.sh, local-k8s.sh (k3d Plan B), import_github_issues.sh
backend/migrations/ Alembic schema migrations
evaluation/         Defect-injection benchmark, PROMISE NFR classifier training
docs/               DEPLOYMENT runbook, architecture decision records, evaluation notes
samples/            Example brief
```

## Quick start (local)

**Option A: Docker Compose (whole stack)**

```bash
cp .env.example .env            # edit secrets
docker compose up --build       # → http://localhost:8080   (API docs: http://localhost:8000/docs)
docker compose --profile monitoring up --build   # + Grafana :3000 (admin/admin), Prometheus :9090
```

**Option C: local Kubernetes (same manifests as production)**: `scripts/local-k8s.sh up` (needs Docker, k3d, kubectl) → http://localhost:8081 and http://localhost:8081/grafana

**Option B: dev mode (hot reload, SQLite, no Docker)**

```bash
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                 # http://localhost:8000/docs

cd ../frontend && npm install && npm run dev  # http://localhost:5173  (proxies /api to :8000)
```

Register an account (the first account becomes **admin**), create a project, click **Use sample brief** and then **Generate blueprint**.

## Tests and quality gates

```bash
cd backend  && ruff check app tests && pytest -q && bandit -r app -c pyproject.toml -ll
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
PYTHONPATH=backend python evaluation/defect_injection.py      # checker benchmark
```

The backend suite (20 tests) covers auth/RBAC, generation, the self-check repair loop, change-impact propagation, baselines and diffs, all export formats, file upload and semantic search. It passes on both SQLite and PostgreSQL + pgvector.

## Configuration

All settings are environment variables. See `backend/app/config.py`; the most important are:

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./specforge.db` | `postgresql+psycopg://…` in production |
| `INLINE_JOBS` | `true` | `false` sends jobs to Celery through `REDIS_URL` |
| `JWT_SECRET` | dev value | **Must** be changed in production (`openssl rand -hex 32`) |
| `LLM_PROVIDER` | `heuristic` | `openai` (any OpenAI-compatible API) or `anthropic` |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` | | e.g. Groq: `https://api.groq.com/openai/v1`, `llama-3.3-70b-versatile` |
| `USE_TRANSFORMER_MODELS` | `false` | `true` = sentence-transformers + NLI cross-encoder (build with `WITH_ML=true`) |
| `STORAGE_BACKEND` | `local` | `s3` with `S3_BUCKET`, using the instance profile |

## Deployment

The full step-by-step runbook (AWS Academy Learner Lab → Terraform → Ansible → GitHub Actions → CloudWatch) is in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**.

## Documentation

- [docs/DEVOPS.md](docs/DEVOPS.md): **how every DevOps tool is integrated, plus the demo script**
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): deployment runbook and troubleshooting
- [docs/EVALUATION.md](docs/EVALUATION.md): how to produce the numbers for the paper
- [docs/adr/](docs/adr/): architecture decision records
- API reference: `/docs` (Swagger UI) or `/openapi.json` on any running instance
