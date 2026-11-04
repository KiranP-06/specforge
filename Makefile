.PHONY: dev test lint up up-mon down eval k8s-up k8s-down migrate
dev:            ## API (SQLite, inline jobs) + Vite dev server
	cd backend && uvicorn app.main:app --reload & cd frontend && npm run dev
test:           ## all tests
	cd backend && pytest -q
	cd frontend && npm test
lint:           ## linters + SAST
	cd backend && ruff check app tests && bandit -q -r app -c pyproject.toml -ll
	cd frontend && npm run lint && npm run typecheck
up:             ## full stack in Docker
	docker compose up --build
down:
	docker compose down
eval:           ## checker benchmark
	PYTHONPATH=backend python evaluation/defect_injection.py
up-mon:         ## full stack + Prometheus/Grafana
	docker compose --profile monitoring up --build
k8s-up:         ## local Kubernetes (k3d) with the production manifests
	scripts/local-k8s.sh up
k8s-down:
	scripts/local-k8s.sh down
migrate:        ## apply DB migrations to $$DATABASE_URL
	cd backend && alembic upgrade head
