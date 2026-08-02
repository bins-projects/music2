from pathlib import Path


WORKBENCH = Path("ingestion_v2/workbench")


def test_workbench_is_private_synthetic_preview_with_no_promotion_action() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")
    data = (WORKBENCH / "demo-data.js").read_text(encoding="utf-8")

    assert "Synthetic preview · no writes" in html
    assert "No canonical write available" in html
    assert "promote_canonical: false" in data
    assert "promote(" not in script
    assert "fetch(" not in script
    assert "localStorage" not in script


def test_workbench_exposes_required_review_information_and_actions() -> None:
    html = (WORKBENCH / "index.html").read_text(encoding="utf-8")
    script = (WORKBENCH / "workbench.js").read_text(encoding="utf-8")

    for required_id in (
        "question-meta",
        "finding-explanation",
        "preserved-value",
        "proposed-value",
        "verification-card",
        "actions",
    ):
        assert f'id="{required_id}"' in html
    for action in ("approve", "reject", "defer", "leave_blocked"):
        assert action in script


def test_workbench_has_responsive_layout() -> None:
    css = (WORKBENCH / "workbench.css").read_text(encoding="utf-8")

    assert "@media (max-width: 850px)" in css
    assert "@media (max-width: 520px)" in css
