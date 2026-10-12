"""HTTP checks of the production Moodle adapter and policy; no live services."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import requests
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.provider_base import LLMResult
from deeptutor_integration.api import create_router
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.service import DeepTutorService

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from course_query_auth import create_moodle_query_authorizer
from grounded_chat_router import create_grounded_chat_router
from lms_chat_router import router as lms_router

PATHS = ["/deeptutor/query", "/chat/grounded", "/lms/chat"]
URL = "https://moodle.test"
COURSES = {11: [{"id": 9, "shortname": "INT1339"}],
           12: [{"id": 10, "shortname": "MATH101"}]}


def payload(path, course="INT1339", kb=None):
    body = {"course_id": course, "question": "What is Python?"}
    if kb is not None:
        body["kb_id" if path == "/deeptutor/query" else "kb_name"] = kb
    return body


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    adapter = MagicMock()
    adapter.get_knowledge_base.return_value = {
        "status": "ready", "statistics": {"rag_initialized": True},
    }
    adapter.search.return_value = {"sources": [{"content": "Python context", "chunk_id": "c1"}]}
    service = DeepTutorService(DeepTutorConfig(tmp_path, tmp_path / "DeepTutor",
                                            tmp_path / "cli.exe", tmp_path / "runtime"), adapter)
    service.query = MagicMock(wraps=service.query)
    orchestrator = MagicMock()
    orchestrator.generate = AsyncMock(return_value=LLMResult("success", "mock", "mock", "Answer", 0))
    authorizer = create_moodle_query_authorizer(service, URL)
    app = FastAPI()
    app.include_router(create_router(service, query_authorizer=authorizer))
    app.include_router(create_grounded_chat_router(service, GroundedChatService(orchestrator),
                                                 query_authorizer=authorizer))
    app.include_router(lms_router)

    def moodle_response(url, **kwargs):
        assert url == f"{URL}/webservice/rest/server.php"
        assert kwargs["allow_redirects"] is False
        assert "params" not in kwargs
        data = kwargs["data"]
        user_id = {"student-a": 11, "student-b": 12}.get(data["wstoken"])
        if user_id is None:
            return httpx.Response(200, json={"errorcode": "invalidtoken", "message": "secret"})
        if data["wsfunction"] == "core_webservice_get_site_info":
            return httpx.Response(200, json={"userid": user_id,"siteurl":URL,"functions":[{"name":"core_enrol_get_users_courses"}]})
        assert data["wsfunction"] == "core_enrol_get_users_courses"
        assert data["userid"] == user_id
        assert data["returnusercount"] == 0
        return httpx.Response(200, json=COURSES[user_id])

    post = MagicMock(side_effect=moodle_response)
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.post", post)
    return TestClient(app), service, adapter, orchestrator, post


def no_retrieval(runtime):
    _, service, adapter, orchestrator, _ = runtime
    service.query.assert_not_called()
    adapter.get_knowledge_base.assert_not_called()
    adapter.search.assert_not_called()
    orchestrator.generate.assert_not_awaited()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("headers", [
    {}, {"X-Internal-Api-Key": "service-token", "X-Verified-Principal": "student-a"},
    {"Authorization": "Basic student-a"}, {"Authorization": "Bearer bad-token"},
])
def test_missing_or_invalid_credentials_are_401_before_retrieval(runtime, path, headers):
    response = runtime[0].post(path, headers=headers, json=payload(path))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "principal_required"
    assert "secret" not in response.text
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("token,course", [("student-a", "MATH101"), ("student-b", "INT1339")])
def test_foreign_course_is_403_even_with_claimed_role_and_student(runtime, path, token, course):
    response = runtime[0].post(path, headers={"Authorization": f"Bearer {token}"},
                               json={**payload(path, course), "student_id": "11", "role": "admin"})
    assert response.status_code == 403
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("course", ["INT1339", " int1339 "])
def test_authorized_request_resolves_scope_and_runs_auth_once(runtime, path, course):
    client, service, adapter, orchestrator, post = runtime
    response = client.post(path, headers={"Authorization": "Bearer student-a"},
                           json=payload(path, course))
    assert response.status_code == 200
    service.query.assert_called_once()
    assert service.query.call_args.args[0].course_id == "INT1339"
    assert service.query.call_args.args[0].kb_id == "int1339-python"
    adapter.search.assert_called_once_with("int1339-python", "What is Python?")
    assert post.call_count == 4  # One credential check and one live enrollment lookup.
    if path == "/deeptutor/query":
        assert response.json()["data"]["course_id"] == "INT1339"
        orchestrator.generate.assert_not_awaited()
    else:
        assert response.json()["kb_name"] == "int1339-python"
        orchestrator.generate.assert_awaited_once()


@pytest.mark.parametrize("path", PATHS)
def test_explicit_foreign_kb_is_rejected_before_retrieval(runtime, path):
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"},
                               json=payload(path, kb="lms-math101"))
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "kb_course_mismatch"
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("failure_call", [1, 2])
def test_auth_dependency_outage_is_safe_503_before_retrieval(runtime, path, failure_call):
    post = runtime[4]
    normal_response = post.side_effect
    calls = 0
    def unavailable(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == failure_call:
            raise requests.ConnectionError("private token=secret")
        return normal_response(*args, **kwargs)
    post.side_effect = unavailable
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "moodle_authorization_unavailable"
    assert "private" not in response.text and "secret" not in response.text
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("result,status", [
    ({"error_type": "retrieval_error", "sources": []}, 502),
    ({"error": "private secret", "sources": []}, 502),
    ({"needs_reindex": True, "sources": []}, 409),
    ([], 502),
])
def test_retrieval_failures_never_become_successful_chat(runtime, path, result, status):
    runtime[2].search.return_value = result
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert response.status_code == status
    runtime[2].search.assert_called_once()
    runtime[3].generate.assert_not_awaited()
    assert "private" not in response.text and "secret" not in response.text


@pytest.mark.parametrize("path", PATHS)
def test_empty_successful_retrieval_remains_safe_no_context(runtime, path):
    runtime[2].search.return_value = {"sources": []}
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert response.status_code == 200
    runtime[2].search.assert_called_once()
    runtime[3].generate.assert_not_awaited()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("courses", [None, [{"id": True, "shortname": "INT1339"}],
                                     [{"id": 9, "shortname": "INT1339"}, {"id": 10, "shortname": "int1339"}]])
def test_invalid_or_ambiguous_authoritative_scope_fails_closed(runtime, path, courses):
    normal_response = runtime[4].side_effect
    runtime[4].side_effect = lambda url, **kw: (
        httpx.Response(200, json=courses) if kw["data"]["wsfunction"] == "core_enrol_get_users_courses"
        else normal_response(url, **kw)
    )
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert response.status_code == 503
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
def test_unconfigured_production_auth_is_fail_closed(runtime, path):
    client, service, _, _, _ = runtime
    missing = create_moodle_query_authorizer(service, None)
    app = FastAPI()
    app.include_router(create_router(service, query_authorizer=missing))
    app.include_router(create_grounded_chat_router(service, None, query_authorizer=missing))
    client = TestClient(app)
    assert client.post(path, json=payload(path)).status_code == 401
    assert client.post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path)).status_code == 503
    runtime[4].assert_not_called()
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
def test_actual_main_composition_injects_the_shared_boundary(runtime, monkeypatch, path):
    import main
    client, service, _, orchestrator, _ = runtime
    # Configure the real registered dependency, keeping the actual main route wiring.
    main.app.dependency_overrides[main.QUERY_AUTHORIZER] = create_moodle_query_authorizer(service, URL)
    monkeypatch.setattr(main.DEEPTUTOR_SERVICE, "query", service.query)
    monkeypatch.setattr(main.GROUNDED_CHAT_SERVICE, "chat", GroundedChatService(orchestrator).chat)
    try:
        response = TestClient(main.app).post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
        assert response.status_code == 200
        assert runtime[4].call_count == (8 if path=="/deeptutor/query" else 10)
        # Production no longer invokes opaque legacy retrieval; an unpublished course is empty/safe.
        service.query.assert_not_called()
        orchestrator.generate.assert_not_awaited()
    finally:
        main.app.dependency_overrides.clear()


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("response", [
    httpx.Response(302, headers={"Location": "https://untrusted.test"}),
    httpx.Response(500, text="private secret"),
    httpx.Response(200, text="not JSON private secret"),
    httpx.Response(200, json={"errorcode": ["private secret"]}),
    httpx.Response(200, json={"userid": True}),
])
def test_malformed_identity_transport_fails_closed_without_leaking(runtime, path, response):
    runtime[4].side_effect = None
    runtime[4].return_value = response
    result = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert result.status_code == 503
    assert "private" not in result.text and "secret" not in result.text
    assert runtime[4].call_count == 1
    no_retrieval(runtime)


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("error,status", [
    ("denied", 403), ("unavailable", 503),
])
def test_routes_honor_shared_policy_denial_before_retrieval(runtime, monkeypatch, path, error, status):
    from deeptutor_integration.auth_contracts import CourseAccessDeniedError, MoodleAuthorizationUnavailableError
    exception = CourseAccessDeniedError() if error == "denied" else MoodleAuthorizationUnavailableError()
    policy = MagicMock(side_effect=exception)
    monkeypatch.setattr("deeptutor_integration.moodle_trust.CourseAuthorizationPolicy.authorize", policy)
    response = runtime[0].post(path, headers={"Authorization": "Bearer student-a"}, json=payload(path))
    assert response.status_code == status
    policy.assert_called_once()
    no_retrieval(runtime)
