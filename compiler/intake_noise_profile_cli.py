import argparse
import json
from pathlib import Path

from compiler.noise_profile import profile_repeated_page_noise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Profile repeated page noise without removing text.")
    parser.add_argument("run_directory", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run = args.run_directory
    raw_path = run / "artifacts" / "01_raw.txt"
    status_path = run / "run-status.json"
    try:
        status = json.loads(status_path.read_text(encoding="utf-8"))
        raw = raw_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"Noise profiling stopped: {error}") from error
    if status.get("run_id") != run.name or status.get("stage") != "cleaning_complete":
        raise SystemExit("Noise profiling stopped: run is not cleaning-complete")
    report = profile_repeated_page_noise(raw)
    report["run_id"] = run.name
    destination = run / "artifacts" / "02_noise-profile.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    status.update(
        repeated_noise_profile_present=True,
        repeated_line_candidates=len(report["line_candidates"]),
        repeated_suffix_candidates=len(report["suffix_candidates"]),
        noise_profile_detection_only=True,
    )
    temporary = status_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    temporary.replace(status_path)
    print("PrepFlow repeated page-noise profile complete")
    print(f"Run: {run.name}")
    print(f"Pages: {report['page_count']}")
    print(f"Repeated line candidates: {len(report['line_candidates'])}")
    print(f"Repeated suffix candidates: {len(report['suffix_candidates'])}")
    print("Detection only: True; text removed: False")


if __name__ == "__main__":
    main()
