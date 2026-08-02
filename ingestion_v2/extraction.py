from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader

from ingestion_v2.domain import DomainError


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    pages: tuple[str, ...]
    adapter_name: str
    page_count: int
    extracted_characters: int


class ExtractionAdapter(Protocol):
    def extract(self, run_directory: Path) -> ExtractionResult: ...


class SyntheticTextExtractionAdapter:
    adapter_name = "synthetic_text_utf8_v1"

    def extract(self, run_directory: Path) -> ExtractionResult:
        data = _read_verified_disposable_copy(run_directory)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise DomainError("Synthetic text staging copy is not valid UTF-8") from error
        pages = tuple(page for page in text.split("\f") if page.strip())
        return _result(pages, self.adapter_name)


class PdfExtractionAdapter:
    adapter_name = "text_pdf_pages_v1"

    def extract(self, run_directory: Path) -> ExtractionResult:
        data = _read_verified_disposable_copy(run_directory)
        try:
            reader = PdfReader(BytesIO(data))
            pages = tuple(
                text
                for page in reader.pages
                if (text := page.extract_text()) and text.strip()
            )
        except Exception as error:
            raise DomainError("PDF extraction failed inside the private run") from error
        return _result(pages, self.adapter_name)


def extract_disposable_copy(run_directory: Path, source_type: str) -> ExtractionResult:
    if source_type == "synthetic_text":
        return SyntheticTextExtractionAdapter().extract(run_directory)
    if source_type == "pdf":
        return PdfExtractionAdapter().extract(run_directory)
    raise DomainError("No extraction adapter exists for this source type")


def _result(pages: tuple[str, ...], adapter_name: str) -> ExtractionResult:
    if not pages:
        raise DomainError("No extractable text was found in the disposable copy")
    text = "\n\f\n".join(pages)
    return ExtractionResult(
        text=text,
        pages=pages,
        adapter_name=adapter_name,
        page_count=len(pages),
        extracted_characters=len(text),
    )


def _read_verified_disposable_copy(run_directory: Path) -> bytes:
    run = Path(run_directory)
    if run.is_symlink() or not run.is_dir() or not run.name.startswith("v2-run-"):
        raise DomainError("Extraction requires a verified private run directory")
    incoming = run / "incoming"
    if incoming.is_symlink() or not incoming.is_dir():
        raise DomainError("Run incoming boundary is missing or unsafe")
    staged = incoming / "source.bin"
    if staged.is_symlink() or not staged.is_file():
        raise DomainError("Disposable staging copy is missing or unsafe")
    if staged.parent.resolve(strict=True) != incoming.resolve(strict=True):
        raise DomainError("Disposable staging copy escaped the run boundary")
    return staged.read_bytes()
