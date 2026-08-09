from ingestion_v2.repair_desk import reconcile_repairs, repair_desk_lookup


def pack(question_id: str, stem: str = "Original") -> dict:
    return {"pack_id": "fundamentals", "questions": [{"id": question_id, "stem": stem, "choices": [{"label": "A", "text": "First"}], "correct_answers": ["A"], "rationale": "Why"}]}


def test_reconciliation_is_field_scoped_and_never_requests_whole_record_copy() -> None:
    records = {"repairs": [{"repair_id": "R-1", "question_id": "PFQ-fundamentals-000000108", "field": "stem", "before": "Original", "after": "Approved"}]}
    result = reconcile_repairs(records, pack("PFQ-fundamentals-000000108"), pack("PFQ-fundamentals-000000108", "Approved"))
    assert result[0]["fields"][0]["status"] == "represented"
    assert result[0]["fields"][0]["field"] == "stem"


def test_reconciliation_marks_newer_parser_disagreement_without_overwriting_it() -> None:
    records = {"repairs": [{"repair_id": "R-1", "question_id": "PFQ-fundamentals-000000108", "field": "stem", "before": "Original", "after": "Approved"}]}
    current = {"PFQ-fundamentals-000000108": pack("PFQ-fundamentals-000000108", "New parser value")["questions"][0]}
    result = reconcile_repairs(records, pack("PFQ-fundamentals-000000108"), pack("PFQ-fundamentals-000000108", "Original"), current)
    assert result[0]["fields"][0]["status"] == "conflicts_with_newer_parser"


def test_lookup_accepts_full_id_and_numeric_suffix_across_all_locations() -> None:
    question_id = "PFQ-fundamentals-000000108"
    records = {"repairs": [{"repair_id": "R-108", "question_id": question_id}]}
    result = repair_desk_lookup("108", canonical_packs=[pack(question_id)], candidate_pack=pack(question_id), repair_records=records, unresolved=[{"question_id": question_id, "finding_id": "F-1"}], excluded=[{"question_id": question_id, "finding_id": "F-2"}])
    assert {item["location"] for item in result["matches"]} == {"canonical_pack", "isolated_candidate", "repair_record", "unresolved_queue", "excluded_record"}
    assert repair_desk_lookup(question_id, canonical_packs=[pack(question_id)])["matches"][0]["question_id"] == question_id


def test_lookup_accepts_friendly_book_reference_without_changing_internal_id() -> None:
    question_id = "PFQ-pediatrics-000000398"
    assert repair_desk_lookup("Peds 398", canonical_packs=[pack(question_id)])["matches"][0]["question_id"] == question_id
    assert repair_desk_lookup("peds398", canonical_packs=[pack(question_id)])["matches"][0]["question_id"] == question_id


def test_lookup_accepts_new_source_friendly_prefix_without_changing_internal_id() -> None:
    question_id = "PFQ-adult_health-000000001"
    result = repair_desk_lookup(
        "adult health1", canonical_packs=[pack(question_id)],
        friendly_prefixes={"adult_health": "Adult Health"},
    )
    assert result["matches"][0]["question_id"] == question_id
