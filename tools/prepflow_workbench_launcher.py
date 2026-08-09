#!/usr/bin/env python3
"""Local-only launcher for the private PrepFlow Workbench."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import json
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen


REPOSITORY = Path("/home/charliekeila/projects/prepflow")
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
HEALTH_URL = f"{URL}api/health"
LOG_LIMIT = 80
SAFE_EVENTS = {"reopened_running_workbench", "started_local_workbench", "port_unavailable", "health_timeout", "stop_requested"}


def runtime_directory(repository: Path = REPOSITORY) -> Path:
    return repository / "output" / "workbench-launcher"


def write_log(event: str, repository: Path = REPOSITORY) -> None:
    """Keep a bounded event-only log; never record command output or user input."""
    directory = runtime_directory(repository)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = directory / "launcher.log"
    prior = deque(path.read_text(encoding="utf-8").splitlines()[-(LOG_LIMIT - 1):] if path.exists() else (), maxlen=LOG_LIMIT - 1)
    prior.append(f"{datetime.now(timezone.utc).isoformat()} {event if event in SAFE_EVENTS else 'event_rejected'}")
    path.write_text("\n".join(prior) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def healthy() -> bool:
    try:
        with urlopen(HEALTH_URL, timeout=0.6) as response:
            return response.status == 200 and json.loads(response.read()) == {"status": "ok", "scope": "local_only"}
    except (URLError, OSError, ValueError):
        return False


def port_in_use() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=0.3):
            return True
    except OSError:
        return False


def notify(message: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "PrepFlow Workbench", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    elif shutil.which("xmessage"):
        subprocess.Popen(["xmessage", "-center", "-title", "PrepFlow Workbench", message], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def open_browser() -> None:
    subprocess.Popen(["xdg-open", URL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def server_command(repository: Path = REPOSITORY) -> list[str]:
    return [str(repository / ".venv" / "bin" / "python"), "-m", "ingestion_v2.workbench_server", "--port", str(PORT)]


def start(repository: Path = REPOSITORY) -> int:
    python = repository / ".venv" / "bin" / "python"
    if not repository.is_dir():
        notify("Repository is unavailable. Check the local PrepFlow checkout.")
        return 2
    if not python.is_file():
        notify("Virtual environment is unavailable. Restore .venv and try again.")
        return 2
    if healthy():
        write_log("reopened_running_workbench", repository)
        open_browser()
        return 0
    if port_in_use():
        notify("Port 8765 is in use by a non-Workbench service.")
        write_log("port_unavailable", repository)
        return 3
    subprocess.Popen(server_command(repository), cwd=repository, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):
        if healthy():
            write_log("started_local_workbench", repository)
            open_browser()
            return 0
        time.sleep(0.15)
    notify("Workbench did not become healthy. Try Restart from the Apps menu.")
    write_log("health_timeout", repository)
    return 4


def stop(repository: Path = REPOSITORY) -> int:
    # The server is intentionally localhost-only; terminate only its exact command.
    result = subprocess.run(["pkill", "-f", "ingestion_v2.workbench_server.*--port 8765"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    write_log("stop_requested", repository)
    notify("Workbench stopped." if result.returncode == 0 else "No running Workbench was found.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the local PrepFlow Workbench.")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.stop:
        return stop()
    if args.restart:
        stop()
        time.sleep(0.3)
    return start()


if __name__ == "__main__":
    raise SystemExit(main())
