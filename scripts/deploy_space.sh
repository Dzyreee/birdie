#!/usr/bin/env bash
# Deploy Birdie to an existing Hugging Face Docker Space with `hf upload` (not git push).
#
# Usage: scripts/deploy_space.sh Affaad/birdiee
# Tracked edits and the explicitly listed integration files are included; media stays excluded.
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
for path in Dockerfile .dockerignore birdie/api.py birdie/vision/demo.py \
  docs/DEMO_BASELINE.md tests/test_api.py tests/test_clip.py \
  tests/test_recorded_demo.py tests/test_seat_association.py; do
  mkdir -p "$STAGE/$(dirname "$path")"
  [ ! -f "$ROOT/$path" ] || cp "$ROOT/$path" "$STAGE/$path"
done
rm -f "$STAGE/CLAUDE.md"

if ! SPACE_SHA="$(hf spaces info "$SPACE_ID" --format json | python -c 'import json, sys; print(json.load(sys.stdin)["sha"])')"; then
  echo "Space $SPACE_ID was not found or is inaccessible; create/check it as a Docker Space first." >&2
  exit 1
fi

REV="$(git -C "$ROOT" rev-parse --short HEAD)"
if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then REV="$REV+worktree"; fi
python - "$SPACE_ID" "$STAGE" "$REV" "$SPACE_SHA" <<'PY'
import sys
from huggingface_hub import HfApi

space_id, stage, revision, parent = sys.argv[1:]
result = HfApi().upload_folder(repo_id=space_id, repo_type="space", folder_path=stage,
                               commit_message=f"Deploy Birdie {revision}", parent_commit=parent)
print(f"Space commit: {result.oid}")
PY

echo "Deployed: https://huggingface.co/spaces/$SPACE_ID"
echo "Build logs: hf spaces logs $SPACE_ID --build --follow"
