import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
sys.path.insert(0, str(Path(__file__).parents[1] / "lms-dlu-demo"))
from legacy_route_security import install_legacy_security


@pytest.fixture
def guarded():
    app=FastAPI(); operation=MagicMock(); lookup=MagicMock(return_value=("owner-B", "COURSE-B"))
    class Access:
        owner_ref="owner-A"
        def require_owner(self, owner):
            if owner != self.owner_ref: raise HTTPException(403)
        def scope(self, course):
            if course != "COURSE-A": raise HTTPException(403)
            return type("Scope", (), {"course_key":course})()
    def auth(request):
        if request.headers.get("Authorization") != "Bearer A": raise HTTPException(401)
        return Access()
    @app.api_route("/{path:path}", methods=["GET","POST","DELETE"])
    def endpoint(path): operation(); return {"ok":True}
    install_legacy_security(app, auth, lookup)
    return TestClient(app), operation, lookup


@pytest.mark.parametrize("path,method,payload", [
    ("/chat/history/owner-B/COURSE-A", "get", None),
    ("/courses/COURSE-A/progress?student_id=owner-B", "get", None),
    ("/courses/COURSE-B/progress?student_id=owner-A", "get", None),
    ("/quiz-attempts/B/submit", "post", {"answers":[]}),
    ("/quiz-attempts/B/review?student_id=owner-A", "get", None),
    ("/flashcards/B/reviews", "post", {"student_id":"owner-A"}),
])
def test_foreign_owner_or_course_denied_before_operation(guarded,path,method,payload):
    client,op,_=guarded
    response=client.request(method,path,headers={"Authorization":"Bearer A"},json=payload)
    assert response.status_code==403; op.assert_not_called()


@pytest.mark.parametrize("path", ["/chat/history/owner-A/COURSE-A","/courses/COURSE-A/progress?student_id=owner-A","/quiz-attempts/B/submit"])
def test_anonymous_rejected_before_owner_lookup(guarded,path):
    client,op,lookup=guarded
    assert client.get(path).status_code==401
    op.assert_not_called(); lookup.assert_not_called()


def test_owned_course_allowed(guarded):
    client,op,_=guarded
    assert client.get("/courses/COURSE-A/progress?student_id=owner-A",headers={"Authorization":"Bearer A"}).status_code==200
    op.assert_called_once()


@pytest.mark.parametrize("path", ["/deeptutor/status","/internal/quizzes","/users","/materials/1/check"])
def test_inventory_and_internal_routes_need_service_evidence(guarded,monkeypatch,path):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN","operator")
    client,op,_=guarded
    assert client.get(path,headers={"Authorization":"Bearer A"}).status_code==401
    op.assert_not_called()
    assert client.get(path,headers={"X-Internal-Api-Key":"operator"}).status_code==200
