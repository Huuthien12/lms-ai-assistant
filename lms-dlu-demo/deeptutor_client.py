import os
from typing import Any, Protocol

import httpx


class DeepTutorAPIClient(Protocol):
    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]: ...
    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]: ...
    def check_readiness(self) -> dict[str, Any]: ...


class MockDeepTutorClient:
    def check_readiness(self) -> dict[str, Any]:
        return {"status": "ready", "components": {
            "deeptutor": "available", "course_kb": "available",
            "ollama": "available", "moodle": "configured",
        }}

    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]:
        return {"document_id": str(resource_id), "course_id": str(course_id_moodle), "kb_id": kb_name or "mock-kb", "action": "add", "status": "ready", "metadata": {}}

    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]:
        return {"status": "success", "answer": "Mock grounded answer.", "course_id": course_id, "kb_name": kb_name or "mock-kb", "sources": [{"title": "mock.pdf", "page": 1, "score": 1.0}], "ai": {"provider": "mock", "model": "mock", "fallback_used": False}}


class RealDeepTutorClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]:
        response = httpx.post(f"{self.base_url}/moodle/resources/ingest", json={"course_id_moodle": course_id_moodle, "resource_id": resource_id, "kb_name": kb_name}, timeout=30)
        response.raise_for_status()
        return response.json()

    def check_readiness(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.base_url}/health/ready", timeout=10)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError("DeepTutor readiness is unavailable.") from exc
        if not isinstance(data, dict) or data.get("status") not in {"ready", "degraded"}:
            raise RuntimeError("DeepTutor readiness is unavailable.")
        return data

    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]:
        response = httpx.post(f"{self.base_url}/chat/grounded", json={"question": question, "course_id": course_id, "kb_name": kb_name}, timeout=120)
        response.raise_for_status()
        return response.json()


def create_deeptutor_client() -> DeepTutorAPIClient:
    use_mock = os.getenv("USE_MOCK_API", "false").strip().lower() in {"1", "true", "yes"}
    if use_mock:
        return MockDeepTutorClient()
    return RealDeepTutorClient(os.getenv("DEEPTUTOR_API_BASE_URL", "http://127.0.0.1:8000"))
