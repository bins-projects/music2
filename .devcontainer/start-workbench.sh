#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

workbench_log="/tmp/prepflow-workbench.log"
workbench_pid="/tmp/prepflow-workbench.pid"

if curl --fail --silent --show-error http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
  exit 0
fi

nohup python -m ingestion_v2.workbench_server --host 0.0.0.0 --port 8765 >"$workbench_log" 2>&1 &
echo "$!" >"$workbench_pid"

for attempt in {1..30}; do
  if curl --fail --silent --show-error http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    echo "PrepFlow Workbench is ready on forwarded port 8765."
    exit 0
  fi
  sleep 1
done

echo "PrepFlow Workbench did not become ready. Startup log:"
sed -n '1,160p' "$workbench_log"
exit 1
