from pathlib import Path


def test_active_quiz_renders_full_copyable_stable_question_id() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    script = Path("web/app.js").read_text(encoding="utf-8")
    css = Path("web/arcade-quiz.css").read_text(encoding="utf-8")

    assert 'id="quiz-question-id"' in html
    assert 'quizQuestionId.textContent = displayQuestionReference(question.id)' in script
    assert "quizQuestionId.title = question.id" in script
    assert "#quiz-screen .quiz-question-id" in css
    assert "user-select: text" in css
