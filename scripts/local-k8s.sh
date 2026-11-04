#!/usr/bin/env bash
# Plan B demo: run the full SPECForge stack (app + Prometheus + Grafana) on a local k3d cluster
# using the SAME Kubernetes manifests as production (deploy/k8s/overlays/local).
#
# Requires: Docker, k3d (https://k3d.io), kubectl.
# Usage:  scripts/local-k8s.sh up      → http://localhost:8081  ·  Grafana http://localhost:8081/grafana
#         scripts/local-k8s.sh rollout → rebuild images and do a rolling update
#         scripts/local-k8s.sh down
set -euo pipefail

CLUSTER=specforge
PORT="${PORT:-8081}"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
TAG="local"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
need() { command -v "$1" >/dev/null || { echo "Missing $1 — install it first."; exit 1; }; }

build_and_import() {
  local sha
  sha="$(git -C "$REPO" rev-parse --short=12 HEAD 2>/dev/null || echo local)"
  log "Building images (GIT_SHA=$sha)"
  docker build -t "specforge-api:$TAG" --build-arg GIT_SHA="$sha" "$REPO/backend"
  docker build -t "specforge-web:$TAG" "$REPO/frontend"
  log "Importing images into the cluster"
  k3d image import -c "$CLUSTER" "specforge-api:$TAG" "specforge-web:$TAG"
}

secrets() {
  local pg jwt
  pg="$(openssl rand -hex 12)"; jwt="$(openssl rand -hex 32)"
  kubectl apply -f "$REPO/deploy/k8s/base/namespace.yaml" -f "$REPO/deploy/k8s/monitoring/namespace.yaml"
  kubectl -n specforge get secret specforge-secrets >/dev/null 2>&1 || kubectl -n specforge create secret generic specforge-secrets \
    --from-literal=POSTGRES_PASSWORD="$pg" --from-literal=JWT_SECRET="$jwt" \
    --from-literal=DATABASE_URL="postgresql+psycopg://specforge:$pg@postgres:5432/specforge" --from-literal=LLM_API_KEY=""
  kubectl -n monitoring get secret grafana-admin >/dev/null 2>&1 || kubectl -n monitoring create secret generic grafana-admin --from-literal=password=admin
}

wait_all() {
  log "Waiting for rollouts"
  for o in statefulset/postgres deployment/redis deployment/api deployment/worker deployment/web; do
    kubectl -n specforge rollout status "$o" --timeout=300s
  done
  for o in deployment/prometheus deployment/grafana daemonset/node-exporter; do
    kubectl -n monitoring rollout status "$o" --timeout=300s
  done
}

case "${1:-up}" in
  up)
    need docker; need k3d; need kubectl
    k3d cluster list "$CLUSTER" >/dev/null 2>&1 || {
      log "Creating k3d cluster '$CLUSTER' (Traefik ingress on localhost:$PORT)"
      k3d cluster create "$CLUSTER" --agents 1 -p "$PORT:80@loadbalancer" --wait
    }
    kubectl config use-context "k3d-$CLUSTER" >/dev/null
    build_and_import
    secrets
    log "Applying deploy/k8s/overlays/local"
    kubectl apply -k "$REPO/deploy/k8s/overlays/local"
    wait_all
    log "Smoke tests"
    bash "$HERE/smoke_test.sh" "http://localhost:$PORT"
    cat <<EOT

  App        http://localhost:$PORT
  Grafana    http://localhost:$PORT/grafana      (admin / admin)
  Prometheus kubectl -n monitoring port-forward svc/prometheus 9090  →  http://localhost:9090
  Pods       kubectl get pods -A
EOT
    ;;
  rollout)
    kubectl config use-context "k3d-$CLUSTER" >/dev/null
    build_and_import
    for d in api worker web; do kubectl -n specforge rollout restart "deployment/$d"; done
    for d in api worker web; do kubectl -n specforge rollout status "deployment/$d" --timeout=300s; done
    bash "$HERE/smoke_test.sh" "http://localhost:$PORT"
    ;;
  down)
    k3d cluster delete "$CLUSTER"
    ;;
  *) echo "usage: $0 up|rollout|down"; exit 2 ;;
esac
