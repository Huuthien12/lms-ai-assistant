from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import NormalizedDocument, SourceDocument
from deeptutor_integration.service import DeepTutorService

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lms-dlu-demo"))
from grounded_chat_router import create_grounded_chat_router
from moodle_ingestion_router import create_moodle_ingestion_router
from readiness_router import create_readiness_router


class FakeDeepTutorAdapter:
    def __init__(self):
        self.ingested_bytes = None
        self.search_calls = []

    def health(self):
        return {"available": True, "status": "available"}

    def get_knowledge_base(self, _kb_id):
        return {"name": "int1339-python", "status": "ready", "statistics": {"rag_initialized": True}}

    def add_document(self, _kb_id, document_path, metadata=None):
        self.ingested_bytes = Path(document_path).read_bytes()
        return {"action": "add"}

    def search(self, kb_id, question):
        self.search_calls.append((kb_id, question))
        return {"answer": "not grounding", "sources": [{
            "content": "A Python function is a named block of statements.",
            "chunk_id": "chapter-1", "title": "Chuong 1.pdf", "score": 0.9,
        }]}


def deeptutor_service(tmp_path):
    adapter = FakeDeepTutorAdapter()
    config = DeepTutorConfig(
        repository_root=tmp_path,
        deeptutor_dir=tmp_path / "DeepTutor",
        executable=tmp_path / "DeepTutor" / "deeptutor.exe",
        runtime_dir=tmp_path / "runtime",
    )
    return DeepTutorService(config, adapter), adapter


def test_moodle_ingestion_uses_the_mapped_kb_and_normalized_markdown(tmp_path):
    service, adapter = deeptutor_service(tmp_path)
    source = SourceDocument(
        course_id="INT1339", document_id="1", filename="Chuong 1.pdf", mime_type="application/pdf",
        source="moodle", metadata={"course_name": "Python"}, content=b"%PDF-exact-bytes",
    )
    normalizer = MagicMock()
    normalizer.normalize.return_value = NormalizedDocument(
        course_id="INT1339", document_id="1", original_filename="Chuong 1.pdf",
        original_mime_type="application/pdf", source="moodle", metadata={"course_name": "Python"},
        sha256="a" * 64, markdown="# Normalized PDF", normalizer_version="test-v1",
    )
    moodle = MagicMock()
    moodle.get_source_document.return_value = source
    app = FastAPI()
    app.include_router(create_moodle_ingestion_router(moodle, service, normalizer=normalizer, service_token="test-moodle-token"))

    response = TestClient(app).post("/moodle/resources/ingest", headers={"X-Internal-Api-Key": "test-moodle-token"}, json={"course_id_moodle": 9, "resource_id": 1})

    assert response.status_code == 200
    assert response.json()["kb_id"] == "int1339-python"
    assert adapter.ingested_bytes == b"# Normalized PDF"
    moodle.get_source_document.assert_called_once_with(9, 1)
    assert "moodle-documents" not in response.text.lower()
    assert "token" not in response.text.lower()


def test_grounded_chat_uses_mapped_retrieval_context_and_local_ollama(tmp_path):
    service, adapter = deeptutor_service(tmp_path)
    app = FastAPI()
    app.include_router(create_grounded_chat_router(
        service, GroundedChatService(AIOrchestrator(OllamaProvider()))
    ))
    model_response = httpx.Response(200, json={"message": {"content": "A function is a named block."}})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=model_response) as post:
        response = TestClient(app).post("/chat/grounded", json={
            "course_id": "INT1339", "question": "What is a Python function?",
        })

    body = response.json()
    assert response.status_code == 200
    assert adapter.search_calls == [("int1339-python", "What is a Python function?")]
    assert body["course_id"] == "INT1339"
    assert body["kb_name"] == "int1339-python"
    assert body["sources"] == [{"source_id": "chapter-1", "title": "Chuong 1.pdf", "score": 0.9}]
    assert body["ai"] == {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": False}
    prompt = post.await_args.kwargs["json"]["messages"][-1]["content"]
    assert "A Python function is a named block of statements." in prompt
    assert "not grounding" not in prompt


def test_readiness_reports_ready_then_safely_degrades(tmp_path):
    service, _adapter = deeptutor_service(tmp_path)
    ollama = MagicMock()
    ollama.health_check = AsyncMock(return_value={"status": "available"})
    app = FastAPI()
    app.include_router(create_readiness_router(service, ollama, object()))

    client = TestClient(app)
    ready = client.get("/health/ready")
    assert ready.json()["status"] == "ready"

    ollama.health_check.side_effect = RuntimeError("D:/private/token=secret")
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["components"]["ollama"] == "unavailable"
    assert "private" not in response.text.lower()
    assert "secret" not in response.text.lower()
    assert "traceback" not in response.text.lower()


def test_conflicting_course_knowledge_base_is_a_safe_422(tmp_path):
    service, adapter = deeptutor_service(tmp_path)
    chat = MagicMock()
    chat.chat = AsyncMock()
    app = FastAPI()
    app.include_router(create_grounded_chat_router(service, chat))

    response = TestClient(app).post("/chat/grounded", json={
        "course_id": "INT1339", "kb_name": "lms-other", "question": "Question",
    })

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "code": "kb_course_mismatch", "message": "Knowledge-base id does not match the course.",
    }
    assert adapter.search_calls == []
    chat.chat.assert_not_awaited()
