from pathlib import Path

from pypdf import PdfReader


def read_pdf_pages(path: Path) -> tuple[str, ...]:
    """Extract text pages without cleaning, parsing, or source metadata."""
    if not path.exists():
        raise FileNotFoundError(f"Source file not found: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF source file: {path}")

    reader = PdfReader(str(path))
    pages: list[str] = []

    for page in reader.pages:
        text = page.extract_text()

        if text:
            pages.append(text)

    if not pages:
        raise ValueError(
            "No extractable text was found. "
            "The PDF may be scanned and require OCR."
        )

    return tuple(pages)


def read_pdf(path: Path) -> str:
    """Extract text from a text-based PDF without cleaning or parsing it."""
    return "\n".join(read_pdf_pages(path))
