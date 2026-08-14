#!/usr/bin/env bash
set -euo pipefail
repository="$(git rev-parse --show-toplevel)"
cd "$repository"
exec .venv/bin/python -m ingestion_v2.prepflow_question_workbench_launcher --repository "$repository" --host 0.0.0.0 --port 8765
