from pathlib import Path

import pytest

from compiler.pdf_reader import read_pdf, read_pdf_pages


def test_pdf_reader_rejects_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        read_pdf(missing)


def test_pdf_reader_rejects_non_pdf_file(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("example", encoding="utf-8")

    with pytest.raises(ValueError, match="Expected a PDF"):
        read_pdf(source)


def test_read_pdf_joins_extracted_pages_without_changing_page_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.pdf"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(
        "compiler.pdf_reader.read_pdf_pages",
        lambda _path: ("First page", "Second page"),
    )

    assert read_pdf(source) == "First page\nSecond page"
