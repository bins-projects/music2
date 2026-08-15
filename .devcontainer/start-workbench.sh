#!/usr/bin/env bash
set -euo pipefail

repository="$(git rev-parse --show-toplevel)"
cd "$repository"

workbench_log="/tmp/prepflow-workbench.log"
workbench_pid="/tmp/prepflow-workbench.pid"
health_url="http://127.0.0.1:8765/api/health"
readiness_url="http://127.0.0.1:8765/api/question-workbench/readiness"

one_click_ready() {
  curl --fail --silent --show-error "$health_url" 2>/dev/null | grep -q '"workbench": "unified"' \
    && curl --fail --silent --show-error "$readiness_url" >/dev/null 2>&1
}

if one_click_ready; then
  exit 0
fi

# Older PrepFlow Workbench servers also reported `workbench: unified` but do not
# expose the one-click question readiness route.  Never accept one of those as
# the Codespaces service: replace only the process occupying PrepFlow's known
# private Workbench port, then launch the publication-aware server below.
if curl --fail --silent --show-error "$health_url" 2>/dev/null | grep -q '"workbench": "unified"'; then
  fuser -k 8765/tcp >/dev/null 2>&1 || true
  rm -f "$workbench_pid"
  sleep 1
elif curl --fail --silent --show-error "$health_url" >/dev/null 2>&1; then
  echo "Port 8765 is occupied by a different service." >&2
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
  if one_click_ready; then
    echo "One-click PrepFlow Workbench is ready on forwarded port 8765."
    exit 0
  fi
  sleep 1
done

echo "One-click PrepFlow Workbench did not become ready. Startup log:"
sed -n "1,160p" "$workbench_log"
exit 1
