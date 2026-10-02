from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from lms_chat_router import create_deeptutor_client, get_client, router


def test_lms_chat_uses_injected_mock_client():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_client] = lambda: create_deeptutor_client()

    response = TestClient(app).post("/lms/chat", json={
        "question": "What is a function?", "course_id": "INT1339", "kb_name": "int1339-python",
    })

    assert response.status_code == 200
    assert response.json()["kb_name"] == "int1339-python"
    assert response.json()["ai"]["provider"] == "mock"
