from pathlib import Path


def test_ingestion_docs_define_pre_intake_safety_contract() -> None:
    architecture = Path("docs/INGESTION_ARCHITECTURE.md").read_text(encoding="utf-8")
    handoff = Path("docs/INGESTION_WORKBENCH_HANDOFF.md").read_text(encoding="utf-8")
    combined = " ".join((architecture + handoff).lower().split())

    required = (
        "disposable staging copy",
        "user’s only original",
        "successful extraction and cleaning",
        "failed intake",
        "explicit cleanup",
        "legacy source-specific cleaning",
        "broad missing-a recovery",
        "proposal does not authorize repair",
    )
    for phrase in required:
        assert phrase in combined


def test_public_study_runtime_has_no_private_factory_dependency() -> None:
    runtime_files = tuple(
        path for path in Path("web").rglob("*")
        if path.is_file() and path.suffix in {".js", ".html", ".css", ".webmanifest"}
    )
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    for forbidden_reference in (
        "ingestion_v2",
        "workbench_server",
        "/api/run",
        "/api/identity",
        "compiler.",
    ):
        assert forbidden_reference not in combined
