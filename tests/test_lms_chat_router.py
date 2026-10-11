from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from lms_chat_router import get_client, router


SERVICE_TOKEN = "test-moodle-token"


def test_lms_proxy_cannot_register_an_unprotected_chat_route():
    assert "/lms/chat" not in {route.path for route in router.routes}


def test_lms_routes_delegate_to_the_client_once(monkeypatch):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN", SERVICE_TOKEN)
    class Client:
        def __init__(self): self.calls = []
        def check_readiness(self): self.calls.append("ready"); return {"status": "ready", "components": {}}
        def ingest_resource(self, course_id_moodle, resource_id, kb_name=None):
            self.calls.append((course_id_moodle, resource_id, kb_name)); return {"status": "ready", "kb_id": kb_name}
    client = Client()
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_client] = lambda: client
    test_client = TestClient(app)
    assert test_client.get("/lms/ready").json()["status"] == "ready"
    assert test_client.post("/lms/resources/ingest", headers={"X-Internal-Api-Key": SERVICE_TOKEN}, json={"course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python"}).json()["kb_id"] == "int1339-python"
    assert client.calls == ["ready", (9, 1, "int1339-python")]


def test_lms_routes_hide_client_failures(monkeypatch):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN", SERVICE_TOKEN)
    class Client:
        def check_readiness(self): raise RuntimeError("secret")
        def ingest_resource(self, *args): raise RuntimeError("secret")
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_client] = Client
    client = TestClient(app)
    for response in (
        client.get("/lms/ready"),
        client.post("/lms/resources/ingest", headers={"X-Internal-Api-Key": SERVICE_TOKEN}, json={"course_id_moodle": 9, "resource_id": 1}),
    ):
        assert "secret" not in response.text


def test_lms_ingestion_rejects_invalid_service_credentials_before_client_call(monkeypatch):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN", SERVICE_TOKEN)

    class Client:
        def __init__(self): self.calls = []
        def ingest_resource(self, *args): self.calls.append(args)

    backend = Client()
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_client] = lambda: backend
    client = TestClient(app)
    for headers in ({}, {"X-Internal-Api-Key": "wrong"}):
        response = client.post("/lms/resources/ingest", headers=headers, json={"course_id_moodle": 9, "resource_id": 1})
        assert response.status_code == 401
    assert backend.calls == []

    monkeypatch.delenv("LMS_MOODLE_DISCOVERY_TOKEN")
    response = client.post("/lms/resources/ingest", headers={"X-Internal-Api-Key": SERVICE_TOKEN}, json={"course_id_moodle": 9, "resource_id": 1})
    assert response.status_code == 503
    assert backend.calls == []
