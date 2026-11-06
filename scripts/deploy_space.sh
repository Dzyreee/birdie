#!/usr/bin/env bash
# Deploy Birdie to a Hugging Face Space with `hf upload` (not git push).
#
# Usage:
#   scripts/deploy_space.sh <owner>/birdie            # Space already exists, or create it on default hardware
#   scripts/deploy_space.sh <owner>/birdie cpu-upgrade  # create with this hardware if it doesn't exist
#
# Only files committed to git are uploaded (git archive HEAD), so .venv/, data/, .env files, videos,
# frames and model weights can never be shipped. CLAUDE.md (internal brief) is left out.
# With a fine-grained token scoped to one Space, run:  HF_TOKEN=hf_xxx scripts/deploy_space.sh owner/birdie
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
  echo "creating Space $SPACE_ID"
  hf repos create "$SPACE_ID" --type space --sdk gradio --public ${FLAVOR:+--flavor "$FLAVOR"}
fi

hf upload "$SPACE_ID" "$STAGE" . --type space \
  --commit-message "Deploy $(git -C "$ROOT" rev-parse --short HEAD)"

echo "Deployed: https://huggingface.co/spaces/$SPACE_ID"
echo "Build logs: hf spaces logs $SPACE_ID --build --follow"
