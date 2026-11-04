#!/usr/bin/env bash
# Create GitHub issues from a SPECForge "GitHub Issues" export.
# Requires the GitHub CLI (gh auth login) and jq.
# Usage: scripts/import_github_issues.sh <export.json> <owner/repo> [--dry-run]
set -euo pipefail
FILE="${1:?export file}"; REPO="${2:?owner/repo}"; DRY="${3:-}"

# Make sure every label exists (gh fails on unknown labels).
jq -r '.[].labels[]' "$FILE" | sort -u | while read -r label; do
  [ -n "$DRY" ] || gh label create "$label" --repo "$REPO" --force >/dev/null
done

count=0
while IFS= read -r issue; do
  title=$(jq -r '.title' <<<"$issue")
  body=$(jq -r '.body' <<<"$issue")
  labels=$(jq -r '.labels | join(",")' <<<"$issue")
  if [ -n "$DRY" ]; then echo "would create: $title  [$labels]"
  else gh issue create --repo "$REPO" --title "$title" --body "$body" --label "$labels" >/dev/null; echo "created: $title"; fi
  count=$((count + 1))
done < <(jq -c '.[]' "$FILE")
echo "$count issue(s) processed"
