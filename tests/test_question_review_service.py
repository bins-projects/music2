import json
from io import BytesIO

import pytest

from ingestion_v2 import question_review_service as service


def test_configuration_requires_url_and_token():
    assert service.configuration({})["configured"] is False
    assert service.configuration({"PREPFLOW_REVIEW_SERVICE_URL": "https://example.test"})["configured"] is False
    config = service.configuration({
        "PREPFLOW_REVIEW_SERVICE_URL": "https://example.test/",
        "PREPFLOW_REVIEW_ADMIN_TOKEN": "secret",
    })
    assert config == {"configured": True, "url": "https://example.test", "token": "secret"}


def test_list_reports_uses_admin_bearer(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"reports": [{"question_id": "PFQ-pediatrics-000000001"}]}).encode()

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["auth"] = request.get_header("Authorization")
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(service, "urlopen", fake_urlopen)
    reports = service.list_reports(environment={
        "PREPFLOW_REVIEW_SERVICE_URL": "https://review.example",
        "PREPFLOW_REVIEW_ADMIN_TOKEN": "abc123",
    })
    assert reports == [{"question_id": "PFQ-pediatrics-000000001"}]
    assert captured == {
        "url": "https://review.example/admin/reports",
        "auth": "Bearer abc123",
        "timeout": 5,
    }


def test_unconfigured_service_fails_closed():
    with pytest.raises(service.QuestionReviewServiceError, match="not configured"):
        service.list_reports(environment={})
