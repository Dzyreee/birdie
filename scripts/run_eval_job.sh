#!/usr/bin/env bash
# Launch the evaluation (jobs/evaluate.py) as a Hugging Face Job on cpu-basic, 20 minute timeout.
# It reads the labelled data from the dataset repo and pushes results.json / results.md to its results/ folder.
#
# Usage:  scripts/run_eval_job.sh <owner>/birdie-eval
#         DRY_RUN=1 scripts/run_eval_job.sh <owner>/birdie-eval   # print the Job config, don't launch
# HF_TOKEN must be set to a token that can read and write the dataset (it is passed as a Job secret).
set -euo pipefail

REPO="${1:?usage: scripts/run_eval_job.sh <owner>/birdie-eval}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARGS=(--flavor cpu-basic --timeout 20m --secrets HF_TOKEN --name birdie-eval)

if [ -n "${DRY_RUN:-}" ]; then
  hf jobs uv run "${ARGS[@]}" --dry-run "$ROOT/jobs/evaluate.py" --dataset "$REPO" --push
  exit 0
fi

JOB_ID="$(hf jobs uv run "${ARGS[@]}" --detach -q "$ROOT/jobs/evaluate.py" --dataset "$REPO" --push | tail -n 1)"
echo "Launched job $JOB_ID (cpu-basic, 20 min timeout)"
echo "Follow the logs:  hf jobs logs $JOB_ID --follow"
echo "Check status:     hf jobs inspect $JOB_ID"
echo "Results:          https://huggingface.co/datasets/$REPO/tree/main/results"
