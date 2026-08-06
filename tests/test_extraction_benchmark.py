from compiler.extraction_benchmark import _audit_summary


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
