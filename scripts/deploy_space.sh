#!/usr/bin/env bash
# Deploy Birdie to an existing Hugging Face Docker Space with `hf upload` (not git push).
#
# Usage: scripts/deploy_space.sh Affaad/birdiee
# Tracked edits are included; untracked files are excluded except Dockerfile and .dockerignore.
set -euo pipefail

SPACE_ID="${1:?usage: scripts/deploy_space.sh <owner>/<docker-space>}"
ROOT="$(git rev-parse --show-toplevel)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

git -C "$ROOT" archive HEAD | tar -x -C "$STAGE"
while IFS= read -r -d '' path; do
  if [ -f "$ROOT/$path" ]; then
    mkdir -p "$STAGE/$(dirname "$path")"
    cp "$ROOT/$path" "$STAGE/$path"
  else
    rm -f "$STAGE/$path"
  fi
done < <(git -C "$ROOT" diff --name-only -z HEAD)
for path in Dockerfile .dockerignore; do
  [ ! -f "$ROOT/$path" ] || cp "$ROOT/$path" "$STAGE/$path"
done
rm -f "$STAGE/CLAUDE.md"

if ! hf spaces info "$SPACE_ID" >/dev/null 2>&1; then
  echo "Space $SPACE_ID was not found or is inaccessible; create/check it as a Docker Space first." >&2
  exit 1
fi

REV="$(git -C "$ROOT" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then REV="$REV+worktree"; fi
hf upload "$SPACE_ID" "$STAGE" . --type space \
	--commit-message "Deploy Birdie $REV"

echo "Deployed: https://huggingface.co/spaces/$SPACE_ID"
echo "Build logs: hf spaces logs $SPACE_ID --build --follow"
