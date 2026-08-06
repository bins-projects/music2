import pytest

from compiler.extraction_benchmark import (
    EXTRACTOR_NAMES,
    _audit_summary,
    run_extraction_benchmark,
)


def test_extraction_benchmark_summary_uses_the_same_audit_metrics() -> None:
    report = {
        "source": {"page_count": 433, "raw_characters": 1000},
        "parse": {"parsed_records": 1043, "parser_finding_count": 20},
        "identity": {
            "exact_matches": 1024,
            "source_review_required": 19,
            "pack_only_records": 16,
        },
    }

    assert _audit_summary(report) == {
        "page_count": 433,
        "raw_characters": 1000,
        "parsed_records": 1043,
        "parser_findings": 20,
        "exact_pack_matches": 1024,
        "source_review_required": 19,
        "pack_only_records": 16,
    }


def test_extraction_benchmark_rejects_unknown_strategy_before_reading_source() -> None:
    with pytest.raises(ValueError, match="Unknown extraction strategy"):
        run_extraction_benchmark(
            "not-needed.pdf",
            {},
            strategies=("unknown",),
        )


def test_extraction_benchmark_exposes_rendered_page_ocr_strategy() -> None:
    assert "tesseract_ocr_v1" in EXTRACTOR_NAMES
