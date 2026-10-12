import sys
from pathlib import Path
from unittest.mock import MagicMock
import httpx
import requests
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from deeptutor_integration.service import DeepTutorService
sys.path.insert(0, str(Path(__file__).parents[1] / "lms-dlu-demo"))
from course_query_auth import create_moodle_query_authorizer
from verified_identity_router import create_identity_router


@pytest.fixture
def client(monkeypatch):
    service = MagicMock()
    service.kb_name.side_effect = DeepTutorService.kb_name
    def transport(url, **kw):
        token = kw["data"]["wstoken"]
        if token == "down": raise requests.ConnectionError("private-token")
        uid = {"A": 1, "B": 2}.get(token)
        if not uid: return httpx.Response(200, json={"errorcode": "invalidtoken"})
        if kw["data"]["wsfunction"] == "core_webservice_get_site_info":
            return httpx.Response(200, json={"userid": uid,"siteurl":"https://moodle.test","functions":[{"name":"core_enrol_get_users_courses"}]})
        return httpx.Response(200, json=[{"id": uid, "shortname": "INT1339" if uid == 1 else "INT2001"}])
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.post", transport)
    app = FastAPI(); app.include_router(create_identity_router(create_moodle_query_authorizer(service, "https://moodle.test")))
    return TestClient(app)


def test_principal_bound_course_visibility(client):
    a = client.get("/auth/me", headers={"Authorization": "Bearer A"}).json()
    b = client.get("/auth/me", headers={"Authorization": "Bearer B"}).json()
    assert a["owner_ref"] != b["owner_ref"]
    assert [c["course_key"] for c in a["courses"]] == ["INT1339"]
    assert a["courses"][0]["kb_name"] == "int1339-python"
    assert [c["course_key"] for c in b["courses"]] == ["INT2001"]
    assert b["courses"][0]["kb_name"] == "lms-int2001"
    assert "Bearer" not in str(a) and "_token" not in str(a)


@pytest.mark.parametrize("token,status", [(None,401),("bad",401),("down",503)])
def test_login_fail_closed(client, token, status):
    r=client.get("/auth/me",headers={} if token is None else {"Authorization": "Bearer "+token})
    assert r.status_code == status and "private-token" not in r.text


def test_lecturer_action_boundary_is_live_exact_and_fails_closed(client):
    from fastapi import Request,HTTPException
    from deeptutor_integration.auth_contracts import CourseAction,MoodleAuthorizationUnavailableError
    service=MagicMock(); service.kb_name.side_effect=DeepTutorService.kb_name
    request=Request({"type":"http","headers":[(b"authorization",b"Bearer A")]})
    access=create_moodle_query_authorizer(service,"https://moodle.test")(request)
    with pytest.raises(HTTPException) as error: access.scope("INT1339",action=CourseAction.SYNC_COURSE_RESOURCE)
    assert error.value.status_code==503
    evidence=MagicMock(); evidence.allows.return_value=True
    access.boundary.capability_evidence=evidence
    assert access.scope("INT1339",action=CourseAction.SYNC_COURSE_RESOURCE).moodle_course_id==1
    evidence.allows.assert_called_with(1,1,"moodle/course:manageactivities")
    app=FastAPI(); app.include_router(create_identity_router(lambda:access))
    assert TestClient(app).get("/auth/me").json()["courses"][0]["can_sync"] is True
    evidence.allows.return_value=False
    with pytest.raises(HTTPException) as error: access.scope("INT1339",action=CourseAction.SYNC_COURSE_RESOURCE)
    assert error.value.status_code==403
    evidence.allows.side_effect=MoodleAuthorizationUnavailableError()
    with pytest.raises(HTTPException) as error: access.scope("INT1339",action=CourseAction.SYNC_COURSE_RESOURCE)
    assert error.value.status_code==503
    assert TestClient(app).get("/auth/me").json()["courses"][0]["can_sync"] is False
