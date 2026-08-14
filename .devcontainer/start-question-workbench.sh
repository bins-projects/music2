#!/usr/bin/env bash
set -euo pipefail
repository="$(git rev-parse --show-toplevel)"
cd "$repository"
exec .venv/bin/python -m ingestion_v2.question_workbench_server --host 127.0.0.1 --port 8766
