from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from lms_chat_router import create_deeptutor_client, get_client, router


def test_lms_chat_uses_injected_mock_client(monkeypatch):
    monkeypatch.setenv("USE_MOCK_API", "true")
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client] = lambda: create_deeptutor_client()

    response = TestClient(app).post("/lms/chat", json={
        "question": "What is a function?", "course_id": "INT1339", "kb_name": "int1339-python",
    })

    assert response.status_code == 200
    assert response.json()["kb_name"] == "int1339-python"
    assert response.json()["ai"]["provider"] == "mock"


def test_lms_routes_delegate_to_the_client_once():
    class Client:
        def __init__(self): self.calls = []
        def check_readiness(self): self.calls.append("ready"); return {"status": "ready", "components": {}}
        def ingest_resource(self, course_id_moodle, resource_id, kb_name=None):
            self.calls.append((course_id_moodle, resource_id, kb_name)); return {"status": "ready", "kb_id": kb_name}
        def chat(self, question, course_id, kb_name=None):
            self.calls.append((question, course_id, kb_name)); return {"status": "success", "answer": "A", "course_id": course_id, "kb_name": kb_name, "sources": [{"source_id": "s1"}], "ai": {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": False}}
    client = Client()
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_client] = lambda: client
    test_client = TestClient(app)
    assert test_client.get("/lms/ready").json()["status"] == "ready"
    assert test_client.post("/lms/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python"}).json()["kb_id"] == "int1339-python"
    chat = test_client.post("/lms/chat", json={"question": "Question", "course_id": "INT1339", "kb_name": "int1339-python"})
    assert chat.json()["sources"] == [{"source_id": "s1"}]
    assert chat.json()["ai"] == {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": False}
    assert client.calls == ["ready", (9, 1, "int1339-python"), ("Question", "INT1339", "int1339-python")]


def test_lms_routes_hide_client_failures():
    class Client:
        def check_readiness(self): raise RuntimeError("secret")
        def ingest_resource(self, *args): raise RuntimeError("secret")
        def chat(self, *args): raise RuntimeError("secret")
    app = FastAPI(); app.include_router(router); app.dependency_overrides[get_client] = Client
    client = TestClient(app)
    for response in (
        client.get("/lms/ready"),
        client.post("/lms/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}),
        client.post("/lms/chat", json={"question": "Question", "course_id": "INT1339"}),
    ):
        assert "secret" not in response.text
