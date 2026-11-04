#!/usr/bin/env bash
# Continuous deployment to k3s, run by the self-hosted GitHub runner on the EC2.
#   1. render the repo's AWS overlay with this commit's image tag + the live cluster's settings
#   2. kubectl apply -k  (images AND manifest changes ship together)
#   3. wait for rolling updates
#   4. smoke test; on any failure, roll every deployment back
# Usage: scripts/deploy.sh <image-tag> <ghcr-owner> [base-url]
set -euo pipefail

TAG="${1:?image tag required}"
OWNER="${2:?ghcr owner required}"
BASE_URL="${3:-http://127.0.0.1}"
NS=specforge
KUBECTL="${KUBECTL:-kubectl}"
DEPLOYS=(api worker web)
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

log() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
cfg() { $KUBECTL -n "$NS" get configmap specforge-config -o "jsonpath={.data.$1}"; }

rollback() {
  log "Deployment failed — rolling back"
  for d in "${DEPLOYS[@]}"; do $KUBECTL -n "$NS" rollout undo "deployment/$d" || true; done
  for d in "${DEPLOYS[@]}"; do $KUBECTL -n "$NS" rollout status "deployment/$d" --timeout=180s || true; done
  exit 1
}

log "Rendering overlay for ${TAG:0:12}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -r "$REPO/deploy/k8s" "$WORK/"
OVERLAY="$WORK/k8s/overlays/aws"
# Settings that Ansible wrote into the cluster (bucket, region, LLM) are read back, so the
# repo never needs to contain environment-specific values.
sed -i \
  -e "s|ghcr.io/OWNER/|ghcr.io/$OWNER/|g" \
  -e "s|newTag: latest|newTag: $TAG|g" \
  "$OVERLAY/kustomization.yaml"
sed -i \
  -e "s|REPLACE_WITH_TERRAFORM_OUTPUT|$(cfg S3_BUCKET)|" \
  -e "s|AWS_REGION: .*|AWS_REGION: $(cfg AWS_REGION)|" \
  -e "s|LLM_PROVIDER: .*|LLM_PROVIDER: $(cfg LLM_PROVIDER)|" \
  -e "s|LLM_BASE_URL: .*|LLM_BASE_URL: $(cfg LLM_BASE_URL)|" \
  -e "s|LLM_MODEL: .*|LLM_MODEL: $(cfg LLM_MODEL)|" \
  "$OVERLAY/configmap-patch.yaml"

log "Server-side dry run"
$KUBECTL apply -k "$OVERLAY" --dry-run=server >/dev/null

log "Applying"
$KUBECTL apply -k "$OVERLAY"
for d in "${DEPLOYS[@]}"; do
  $KUBECTL -n "$NS" annotate "deployment/$d" kubernetes.io/change-cause="deploy ${TAG:0:12} $(date -u +%FT%TZ)" --overwrite >/dev/null
done

log "Waiting for rolling updates"
for d in "${DEPLOYS[@]}"; do
  $KUBECTL -n "$NS" rollout status "deployment/$d" --timeout=300s || rollback
done

log "Smoke tests"
bash "$HERE/smoke_test.sh" "$BASE_URL" "${TAG:0:12}" || rollback

log "Deployed ${TAG:0:12} successfully"
$KUBECTL -n "$NS" get pods -o wide
