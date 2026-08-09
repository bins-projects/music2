#!/usr/bin/env python3
"""Install or update the local Apps-menu entry for the private workbench."""
from __future__ import annotations

from pathlib import Path
import os
import shutil


REPOSITORY = Path("/home/charliekeila/projects/prepflow")
APPLICATIONS = Path.home() / ".local" / "share" / "applications"
ICON = REPOSITORY / "tools" / "prepflow-workbench.svg"
LAUNCHER = REPOSITORY / "tools" / "prepflow_workbench_launcher.py"


def desktop_entry(action: str = "") -> str:
    suffix = f" {action}" if action else ""
    return f"[Desktop Entry]\nType=Application\nName=PrepFlow Workbench\nComment=Private local ingestion and repair workbench\nExec={LAUNCHER}{suffix}\nIcon={ICON}\nTerminal=false\nCategories=Education;Development;\nActions=stop;restart;\n\n[Desktop Action stop]\nName=Stop PrepFlow Workbench\nExec={LAUNCHER} --stop\n\n[Desktop Action restart]\nName=Restart PrepFlow Workbench\nExec={LAUNCHER} --restart\n"


def install() -> Path:
    if not REPOSITORY.is_dir() or not LAUNCHER.is_file() or not ICON.is_file():
        raise SystemExit("PrepFlow launcher files are unavailable in the local checkout.")
    APPLICATIONS.mkdir(parents=True, exist_ok=True)
    os.chmod(LAUNCHER, 0o755)
    destination = APPLICATIONS / "prepflow-workbench.desktop"
    destination.write_text(desktop_entry(), encoding="utf-8")
    os.chmod(destination, 0o644)
    if shutil.which("update-desktop-database"):
        os.system(f"update-desktop-database {APPLICATIONS}")
    return destination


if __name__ == "__main__":
    print(install())
