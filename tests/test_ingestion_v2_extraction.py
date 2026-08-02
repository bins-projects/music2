from pathlib import Path

import pytest

from ingestion_v2.domain import DomainError
from ingestion_v2.extraction import PdfExtractionAdapter, extract_disposable_copy
from ingestion_v2.run_lifecycle import RunLifecycle


def staged_run(tmp_path: Path, content: bytes, source_type: str) -> RunLifecycle:
    run = RunLifecycle.create(tmp_path / "runs")
    run.stage_disposable_copy(content, source_type=source_type)
    return run


def test_synthetic_adapter_preserves_page_boundaries_and_reports_counts(tmp_path) -> None:
    run = staged_run(tmp_path, b"First page\fSecond page", "synthetic_text")

    result = extract_disposable_copy(run.run_directory, "synthetic_text")

    assert result.pages == ("First page", "Second page")
    assert result.text == "First page\n\f\nSecond page"
    assert result.page_count == 2
    assert result.extracted_characters == len(result.text)
    assert result.adapter_name == "synthetic_text_utf8_v1"


def test_pdf_adapter_extracts_pages_without_returning_metadata(tmp_path, monkeypatch) -> None:
    run = staged_run(tmp_path, b"synthetic pdf bytes", "pdf")

    class Page:
        def __init__(self, text):
            self.text = text

        def extract_text(self):
            return self.text

    class Reader:
        def __init__(self, _stream):
            self.pages = [Page("First PDF page"), Page("Second PDF page")]

    monkeypatch.setattr("ingestion_v2.extraction.PdfReader", Reader)

    result = PdfExtractionAdapter().extract(run.run_directory)

    assert result.pages == ("First PDF page", "Second PDF page")
    assert not hasattr(result, "filename")
    assert not hasattr(result, "source_path")
    assert not hasattr(result, "metadata")


def test_adapter_rejects_unverified_directory_and_staged_symlink(tmp_path) -> None:
    ordinary = tmp_path / "ordinary"
    ordinary.mkdir()
    with pytest.raises(DomainError, match="verified private run"):
        extract_disposable_copy(ordinary, "synthetic_text")

    run = staged_run(tmp_path, b"copy", "synthetic_text")
    staged = run.run_directory / "incoming" / "source.bin"
    staged.unlink()
    external = tmp_path / "original.txt"
    external.write_text("original")
    staged.symlink_to(external)

    with pytest.raises(DomainError, match="missing or unsafe"):
        extract_disposable_copy(run.run_directory, "synthetic_text")
    assert external.read_text() == "original"


def test_pdf_adapter_reports_scanned_or_empty_document_without_source_identity(tmp_path, monkeypatch) -> None:
    run = staged_run(tmp_path, b"synthetic pdf bytes", "pdf")

    class Reader:
        def __init__(self, _stream):
            self.pages = []

    monkeypatch.setattr("ingestion_v2.extraction.PdfReader", Reader)

    with pytest.raises(DomainError, match="No extractable text") as error:
        PdfExtractionAdapter().extract(run.run_directory)
    assert str(tmp_path) not in str(error.value)
