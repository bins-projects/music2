"""Client for the public PrepFlow question-review mailbox."""
from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class QuestionReviewServiceError(RuntimeError):
    pass


def configuration(environment: dict[str, str] | None = None) -> dict:
    env = os.environ if environment is None else environment
    url = str(env.get("PREPFLOW_REVIEW_SERVICE_URL") or "").strip().rstrip("/")
    token = str(env.get("PREPFLOW_REVIEW_ADMIN_TOKEN") or "").strip()
    return {
        "configured": bool(url and token),
        "url": url,
        "token": token,
    }


def _request(method: str, path: str, *, environment: dict[str, str] | None = None) -> dict:
    config = configuration(environment)
    if not config["configured"]:
        raise QuestionReviewServiceError("Question review service is not configured")

    request = Request(
        f'{config["url"]}{path}',
        method=method,
        headers={
            "Accept": "application/json",
            "Authorization": f'Bearer {config["token"]}',
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("error") or detail
        except json.JSONDecodeError:
            message = detail
        raise QuestionReviewServiceError(f"Review service returned HTTP {error.code}: {message}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise QuestionReviewServiceError(f"Review service is unavailable: {error}") from error

    try:
        result = json.loads(payload)
    except json.JSONDecodeError as error:
        raise QuestionReviewServiceError("Review service returned invalid JSON") from error
    if not isinstance(result, dict):
        raise QuestionReviewServiceError("Review service returned an invalid payload")
    return result


def list_reports(*, environment: dict[str, str] | None = None) -> list[dict]:
    result = _request("GET", "/admin/reports", environment=environment)
    reports = result.get("reports")
    if not isinstance(reports, list):
        raise QuestionReviewServiceError("Review service response is missing reports")
    return [item for item in reports if isinstance(item, dict)]


def clear_report(question_id: str, *, environment: dict[str, str] | None = None) -> bool:
    result = _request(
        "DELETE",
        f"/admin/reports/{quote(str(question_id), safe='')}",
        environment=environment,
    )
    return bool(result.get("deleted"))
