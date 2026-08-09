import importlib.util
from pathlib import Path


LAUNCHER_PATH = Path("tools/prepflow_workbench_launcher.py")
INSTALLER_PATH = Path("tools/install_prepflow_workbench_launcher.py")


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_launcher_reopens_healthy_local_workbench_without_duplicate(tmp_path, monkeypatch) -> None:
    launcher = load(LAUNCHER_PATH, "workbench_launcher_test")
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").touch()
    opened = []
    monkeypatch.setattr(launcher, "healthy", lambda: True)
    monkeypatch.setattr(launcher, "open_browser", lambda: opened.append(True))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("duplicate server")))
    assert launcher.start(tmp_path) == 0
    assert opened == [True]
    assert "reopened_running_workbench" in (tmp_path / "output" / "workbench-launcher" / "launcher.log").read_text()


def test_launcher_reports_missing_repository_and_keeps_logs_content_free(tmp_path, monkeypatch) -> None:
    launcher = load(LAUNCHER_PATH, "workbench_launcher_failure_test")
    notices = []
    monkeypatch.setattr(launcher, "notify", notices.append)
    assert launcher.start(tmp_path / "missing") == 2
    launcher.write_log("patient name / private source answer", tmp_path)
    log = (tmp_path / "output" / "workbench-launcher" / "launcher.log").read_text()
    assert notices and "Repository" in notices[0]
    assert "patient name" not in log and "private source" not in log
    assert "event_rejected" in log


def test_launcher_is_loopback_only_and_installer_has_no_terminal() -> None:
    launcher = load(LAUNCHER_PATH, "workbench_launcher_loopback_test")
    installer = load(INSTALLER_PATH, "workbench_installer_test")
    assert launcher.URL == "http://127.0.0.1:8765/"
    assert "--port" in launcher.server_command()
    entry = installer.desktop_entry()
    assert "Terminal=false" in entry
    assert "Actions=stop;restart;" in entry
    assert "--stop" in entry and "--restart" in entry


def test_launcher_has_non_terminal_feedback_fallback() -> None:
    launcher = load(LAUNCHER_PATH, "workbench_launcher_feedback_test")
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    assert "notify-send" in source
    assert "xmessage" in source
    assert "Terminal=false" in INSTALLER_PATH.read_text(encoding="utf-8")
