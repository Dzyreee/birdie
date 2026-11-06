#!/usr/bin/env bash
# Deploy Birdie to a Hugging Face Docker Space with `hf upload` (not git push).
#
# Usage:
#   scripts/deploy_space.sh affaad/birdie                 # the main Space
#   HF_TOKEN=hf_xxx scripts/deploy_space.sh affaad/birdie  # with a fine-grained token scoped to that Space
#
# Only files committed to git are uploaded (git archive HEAD), so .venv/, data/, eval_data/, .env files,
# videos, frames and model weights can never be shipped. Uncommitted edits are NOT deployed.
# CLAUDE.md (the internal brief) is left out. The Dockerfile in the repo builds the image (python app.py, 7860).
set -euo pipefail

SPACE_ID="${1:?usage: scripts/deploy_space.sh <owner>/birdie [hardware]}"
FLAVOR="${2:-}"
ROOT="$(git rev-parse --show-toplevel)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

if [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]; then
  echo "warning: uncommitted changes are NOT deployed (only HEAD is)" >&2
fi

git -C "$ROOT" archive HEAD | tar -x -C "$STAGE"
rm -f "$STAGE/CLAUDE.md"

if ! hf spaces info "$SPACE_ID" >/dev/null 2>&1; then
  echo "creating Docker Space $SPACE_ID"
  hf repos create "$SPACE_ID" --type space --sdk docker --public ${FLAVOR:+--flavor "$FLAVOR"}
fi

hf upload "$SPACE_ID" "$STAGE" . --type space \
  --commit-message "Deploy $(git -C "$ROOT" rev-parse --short HEAD)"

# Remove files left on the Space by earlier deploys that are no longer in the repo (keeps .gitattributes).
STALE="$(hf spaces list "$SPACE_ID" --recursive --format json | python3 -c '
import json, os, sys
stage = sys.argv[1]
for entry in json.load(sys.stdin):
    path = entry.get("path", "")
    if "tree_id" in entry or path == ".gitattributes":
        continue  # folders, and the Space'"'"'s own attributes file
    if not os.path.exists(os.path.join(stage, path)):
        print(path)
' "$STAGE")"
if [ -n "$STALE" ]; then
  echo "removing stale files from the Space:"; echo "$STALE" | sed 's/^/  /'
  # shellcheck disable=SC2086
  hf repos delete-files "$SPACE_ID" $STALE --type space --commit-message "Remove files no longer in the repo"
fi

echo "Deployed: https://huggingface.co/spaces/$SPACE_ID"
echo "Build logs: hf spaces logs $SPACE_ID --build --follow"
