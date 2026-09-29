from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from readiness_router import create_readiness_router


def client(deeptutor, ollama, moodle):
    app = FastAPI()
    app.include_router(create_readiness_router(deeptutor, ollama, moodle))
    return TestClient(app)


def ready_deeptutor():
    service = MagicMock()
    service.health.return_value = {"status": "available", "available": True}
    service.kb_name.return_value = "int1339-python"
    return service


def test_readiness_is_ready_when_all_existing_components_are_available():
    ollama = MagicMock()
    ollama.health_check = AsyncMock(return_value={"status": "available"})

    response = client(ready_deeptutor(), ollama, object()).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "components": {
        "deeptutor": "available", "course_kb": "available",
        "ollama": "available", "moodle": "configured",
    }}


def test_unavailable_ollama_degrades_without_exposing_errors_or_paths():
    ollama = MagicMock()
    ollama.health_check = AsyncMock(side_effect=RuntimeError("D:/private/token=secret"))

    response = client(ready_deeptutor(), ollama, object()).get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["ollama"] == "unavailable"
    assert "private" not in response.text.lower()
    assert "secret" not in response.text.lower()


def test_missing_component_degrades_deterministically():
    deeptutor = MagicMock()
    deeptutor.health.side_effect = RuntimeError("unavailable")
    deeptutor.kb_name.side_effect = RuntimeError("unavailable")
    ollama = MagicMock()
    ollama.health_check = AsyncMock(return_value={"status": "available"})

    response = client(deeptutor, ollama, None).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "degraded", "components": {
        "deeptutor": "unavailable", "course_kb": "unavailable",
        "ollama": "available", "moodle": "unconfigured",
    }}
