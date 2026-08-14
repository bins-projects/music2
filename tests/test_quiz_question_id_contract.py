from pathlib import Path


def test_active_quiz_shows_stable_reference_and_local_copy_actions() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")
    rules = Path("web/question-reference-rules.js").read_text(encoding="utf-8")
    css = Path("web/arcade-quiz.css").read_text(encoding="utf-8")
    mobile_css = Path("web/mobile-portrait.css").read_text(encoding="utf-8")

    for element_id in ("quiz-question-id", "copy-question-id", "copy-question-report", "quiz-position"):
        assert f'id="{element_id}"' in html
    assert "currentQuestionReference().packPath" in script
    assert "displayQuestionReference(questionPack?.title, question.id)" in script
    assert "copyTextLocally" in script and "navigator.clipboard" in script
    assert "Quiz-session position:" in rules
    assert "Reference unavailable" in rules
    assert "• Ref ${Number(match[2])}" in rules
    for label in ("Pack:", "Chapter:", "Concise reference:", "Full PFQ ID:", "Question type:", "Stem:"):
        assert label in rules
    assert "#quiz-screen .quiz-reference-bar" in css
    assert "grid-template-rows: auto auto auto minmax(0, 1fr) auto" in css
    assert "align-content: start" in css
    assert "grid-row: 5 !important" in mobile_css
    assert "user-select: text" in css
