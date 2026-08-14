#!/usr/bin/env bash
set -euo pipefail

repository="$(git rev-parse --show-toplevel)"
cd "$repository"

workbench_log="/tmp/prepflow-workbench.log"
workbench_pid="/tmp/prepflow-workbench.pid"
health_url="http://127.0.0.1:8765/api/health"

unified_ready() {
  curl --fail --silent --show-error "$health_url" 2>/dev/null | grep -q '"workbench": "unified"'
}

if unified_ready; then
  exit 0
fi

if curl --fail --silent --show-error "$health_url" >/dev/null 2>&1; then
  echo "Port 8765 is occupied by a different PrepFlow service." >&2
  exit 1
fi

python_bin="$repository/.venv/bin/python"
if [[ ! -x "$python_bin" ]]; then
  python_bin="python"
fi

nohup "$python_bin" -m ingestion_v2.prepflow_question_workbench_launcher \
  --repository "$repository" --host 0.0.0.0 --port 8765 >"$workbench_log" 2>&1 &
echo "$!" >"$workbench_pid"

for attempt in {1..30}; do
  if unified_ready; then
    echo "Unified PrepFlow Workbench is ready on forwarded port 8765."
    exit 0
  fi
  sleep 1
done

echo "Unified PrepFlow Workbench did not become ready. Startup log:"
sed -n "1,160p" "$workbench_log"
exit 1
