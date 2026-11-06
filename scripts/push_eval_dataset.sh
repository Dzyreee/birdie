#!/usr/bin/env bash
# Upload the labelled evaluation data to a PRIVATE Hugging Face dataset with `hf upload`.
#
# Usage: scripts/push_eval_dataset.sh <owner>/birdie-eval
#
# Only these files are uploaded, nothing else:
#   <clip_id>/frames/*.jpg   frames with people pixelated (originals are never written)
#   <clip_id>/frames/*.json  detections (normalised boxes) and timestamps
#   <clip_id>/seats.json, <clip_id>/labels.jsonl, <clip_id>/meta.json
# Clip folders are skipped unless meta.json says they were made by tools/extract_frames.py
# ("originals_saved": false). Source videos (eval_clips/) and results/ are never uploaded.
set -euo pipefail

REPO="${1:?usage: scripts/push_eval_dataset.sh <owner>/birdie-eval}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$ROOT/eval_data"
[ -d "$DATA" ] || { echo "No eval_data/ folder: label some clips first (docs/LABELLING.md)." >&2; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

clips=0
files=0
for dir in "$DATA"/*/; do
  dir="${dir%/}"
  name="$(basename "$dir")"
  [ "$name" = "results" ] && continue
  if [ ! -f "$dir/meta.json" ] || ! grep -q '"originals_saved": false' "$dir/meta.json"; then
    echo "skipping $name: not made by tools/extract_frames.py" >&2
    continue
  fi
  mkdir -p "$STAGE/$name/frames"
  for f in seats.json labels.jsonl meta.json; do
    if [ -f "$dir/$f" ]; then cp "$dir/$f" "$STAGE/$name/"; files=$((files + 1)); fi
  done
  for f in "$dir"/frames/*.jpg "$dir"/frames/*.json; do
    [ -f "$f" ] || continue
    cp "$f" "$STAGE/$name/frames/"
    files=$((files + 1))
  done
  clips=$((clips + 1))
done
[ "$clips" -gt 0 ] || { echo "Nothing to upload." >&2; exit 1; }
echo "Uploading $clips clip(s), $files files to $REPO (private)"

if ! hf datasets info "$REPO" >/dev/null 2>&1; then
  hf repos create "$REPO" --type dataset --private
fi
if hf datasets info "$REPO" --format json 2>/dev/null | grep -q '"private": false'; then
  echo "WARNING: $REPO is PUBLIC. Make it private on the Hub before sharing labels you don't want published." >&2
fi
hf upload "$REPO" "$STAGE" . --type dataset --commit-message "Evaluation data: $clips clips"
echo "Done: https://huggingface.co/datasets/$REPO"
