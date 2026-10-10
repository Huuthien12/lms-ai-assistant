from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException

from deeptutor_integration.api import create_router
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import QueryInput
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService


READY = {"name": "int1339-python", "status": "ready", "statistics": {"rag_initialized": True}}
QUERY = {"course_id": "INT1339", "question": "What is Python?"}
IDENTITY_COURSES = {"student-a": {"INT1339"}, "student-b": {"MATH101"}}


class RecordingAdapter:
    def __init__(self, search_error: DeepTutorError | None = None):
        self.search_calls = []
        self.search_error = search_error

    def get_knowledge_base(self, kb_id):
        return READY

    def search(self, kb_id, question):
        self.search_calls.append((kb_id, question))
        if self.search_error:
            raise self.search_error
        return {"answer": "grounded", "sources": [{"course_id": "untrusted-source-claim"}]}


class RecordingService(DeepTutorService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_calls = []

    def query(self, request):
        self.query_calls.append(request)
        return super().query(request)


def verified_query_authorizer(x_verified_principal: str | None = Header(default=None)):
    allowed_courses = IDENTITY_COURSES.get(x_verified_principal or "")
    if allowed_courses is None:
        raise HTTPException(status_code=401, detail={"code": "query_identity_required", "message": "Verified identity is required."})

    def authorize_query(request):
        if request.course_id.upper() not in allowed_courses:
            raise HTTPException(status_code=403, detail={"code": "course_access_denied", "message": "Course access is denied."})

    return authorize_query


def query_app(*, authorizer=verified_query_authorizer, search_error: DeepTutorError | None = None):
    root = Path(__file__).resolve().parents[1]
    adapter = RecordingAdapter(search_error)
    service = RecordingService(DeepTutorConfig(root, root / "DeepTutor", root / "deeptutor.exe", root / "runtime", 30), adapter)
    app = FastAPI()
    router = create_router(service, query_authorizer=authorizer)
    app.state.query_endpoint = next(route.endpoint for route in router.routes if route.path == "/deeptutor/query")
    app.include_router(router)
    return app, adapter, service


def query_endpoint(app):
    return app.state.query_endpoint


@pytest.mark.parametrize("principal", [None, "unknown-principal"])
def test_query_rejects_missing_or_invalid_identity_before_retrieval(principal):
    app, adapter, service = query_app()
    with pytest.raises(HTTPException) as raised:
        verified_query_authorizer(principal)

    assert raised.value.status_code == 401
    assert adapter.search_calls == []
    assert service.query_calls == []


@pytest.mark.parametrize(("principal", "course_id"), [("student-b", "INT1339"), ("student-a", "MATH101")])
def test_query_rejects_verified_identity_without_requested_course_access(principal, course_id):
    app, adapter, service = query_app()
    authorize_query = verified_query_authorizer(principal)
    with pytest.raises(HTTPException) as raised:
        query_endpoint(app)(QueryInput(**{**QUERY, "course_id": course_id}), authorize_query)

    assert raised.value.status_code == 403
    assert adapter.search_calls == []
    assert service.query_calls == []


def test_query_fails_closed_without_an_authorizer():
    app, adapter, service = query_app(authorizer=None)
    with pytest.raises(HTTPException) as raised:
        query_endpoint(app)(QueryInput(**QUERY))

    assert raised.value.status_code == 503
    assert adapter.search_calls == []
    assert service.query_calls == []


def test_query_fails_closed_when_authorizer_cannot_provide_a_course_checker():
    app, adapter, service = query_app()
    with pytest.raises(HTTPException) as raised:
        query_endpoint(app)(QueryInput(**QUERY), None)

    assert raised.value.status_code == 503
    assert adapter.search_calls == []
    assert service.query_calls == []


def test_query_allows_verified_identity_for_its_enrolled_course_without_treating_source_metadata_as_authorization():
    app, adapter, service = query_app()
    response = query_endpoint(app)(QueryInput(**QUERY), verified_query_authorizer("student-a"))

    assert response.success is True
    assert response.data["result"]["sources"][0]["course_id"] == "untrusted-source-claim"
    assert adapter.search_calls == [("int1339-python", "What is Python?")]
    assert len(service.query_calls) == 1


def test_query_rejects_course_kb_mismatch_before_retrieval():
    app, adapter, service = query_app()
    with pytest.raises(HTTPException) as raised:
        query_endpoint(app)(QueryInput(**{**QUERY, "kb_id": "lms-int1339"}), verified_query_authorizer("student-a"))

    assert raised.value.status_code == 422
    assert raised.value.detail["code"] == "kb_course_mismatch"
    assert adapter.search_calls == []
    assert len(service.query_calls) == 1


def test_query_retrieval_failure_does_not_leak_sensitive_details():
    error = DeepTutorError("process_failure", "DeepTutor command failed.", status_code=502, details={"token": "secret-value"})
    app, adapter, service = query_app(search_error=error)
    with pytest.raises(HTTPException) as raised:
        query_endpoint(app)(QueryInput(**QUERY), verified_query_authorizer("student-a"))

    assert raised.value.status_code == 502
    assert raised.value.detail == {"code": "process_failure", "message": "DeepTutor command failed."}
    assert "secret-value" not in str(raised.value.detail)
    assert adapter.search_calls == [("int1339-python", "What is Python?")]
    assert len(service.query_calls) == 1
