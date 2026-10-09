from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.services.ai.grounded_chat import GroundedChatResponse, GroundedChatService
from backend.services.ai.provider_base import LLMResult
from deeptutor_integration.contracts import NormalizedDocument
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from grounded_chat_router import create_grounded_chat_router, retrieved_contexts


class FakeDeepTutor:
    def __init__(self, result: dict, error: DeepTutorError | None = None):
        self.result, self.error = result, error
        self.kb_calls, self.query_calls = [], []

    def kb_name(self, course_id, kb_name):
        self.kb_calls.append((course_id, kb_name))
        return kb_name or ("int1339-python" if course_id == "INT1339" else f"lms-{course_id.lower()}")

    def query(self, request):
        self.query_calls.append(request)
        if self.error:
            raise self.error
        return {"course_id": request.course_id, "kb_id": request.kb_id, "result": self.result}


def client(service, chat_service):
    app = FastAPI()
    app.include_router(create_grounded_chat_router(service, chat_service))
    return TestClient(app)


def test_maps_verified_deeptutor_sources_without_fabricating_fields():
    contexts = retrieved_contexts({"sources": [{
        "content": "Retrieved excerpt", "chunk_id": "chunk-1", "title": "chapter.pdf",
        "source": "D:/kb/chapter.pdf", "page": "4", "score": 0.0325,
    }]})
    assert len(contexts) == 1
    assert contexts[0].text == "Retrieved excerpt"
    assert contexts[0].source_id == "chunk-1"
    assert contexts[0].title == "chapter.pdf"
    assert contexts[0].url is None
    assert contexts[0].score == 0.0325
    assert contexts[0].metadata == {"page": "4"}


def test_normalized_moodle_citations_prefer_original_filename_and_legacy_falls_back():
    formats = ("lecture.pdf", "lecture.docx", "lecture.pptx", "lecture.md")
    for original_filename in formats:
        contexts = retrieved_contexts({"sources": [{
            "content": "Retrieved excerpt", "chunk_id": "chunk-1", "title": "1-hash.md",
            "metadata": {
                "original_filename": original_filename, "source_sha256": "a" * 64,
                "token": "private", "download_url": "https://private", "path": "D:/private",
            },
        }]})
        assert contexts[0].title == original_filename
        assert "hash.md" not in contexts[0].title
    assert retrieved_contexts({"sources": [{"content": "legacy", "title": "legacy.pdf"}]} )[0].title == "legacy.pdf"


def test_generated_moodle_titles_resolve_through_ledger_without_guessing_unknowns():
    with TemporaryDirectory() as directory:
        ledger = MoodleIngestionLedger(Path(directory))
        for document_id, original_filename in enumerate(
            ("lecture.pdf", "lecture.docx", "lecture.pptx", "lecture.md"), start=1
        ):
            sha256 = f"{document_id:x}" * 64
            ledger.record(NormalizedDocument(
                document_id=str(document_id), course_id="INT1339",
                original_filename=original_filename, original_mime_type="application/octet-stream",
                source="moodle", sha256=sha256, markdown="fixture", normalizer_version="test-v1",
            ))
            contexts = retrieved_contexts({"sources": [{
                "content": "Retrieved excerpt", "title": f"{document_id}-{sha256}.md",
            }]}, ledger, "INT1339")
            assert contexts[0].title == original_filename
        unknown = retrieved_contexts({"sources": [{
            "content": "Retrieved excerpt", "title": f"99-{'f' * 64}.md",
        }]}, ledger, "INT1339")
        assert unknown[0].title == f"99-{'f' * 64}.md"


def test_public_endpoint_omits_internal_source_metadata():
    deeptutor = FakeDeepTutor({"sources": [{
        "content": "Retrieved excerpt", "chunk_id": "chunk-1", "title": "chapter.pdf",
        "source": "D:/runtime/chapter.pdf", "page": 4, "score": 0.5,
    }]})
    orchestrator = MagicMock()
    orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="ollama", model="qwen2.5:3b", content="Grounded answer.",
        latency_ms=1.0, fallback_used=False,
    ))

    response = client(deeptutor, GroundedChatService(orchestrator)).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"}
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Grounded answer."
    assert response.json()["sources"] == [{
        "source_id": "chunk-1", "title": "chapter.pdf", "page": 4, "score": 0.5,
    }]
    assert "runtime" not in response.text.lower()


def test_endpoint_preserves_contract_and_never_uses_generated_answer_as_context():
    deeptutor = FakeDeepTutor({
        "answer": "generated answer that must not be context",
        "content": "also generated answer",
        "sources": [{"content": "retrieved text", "chunk_id": "c1", "title": "doc.pdf", "score": 0.5}],
    })
    chat_service = MagicMock()
    chat_service.chat = AsyncMock(return_value=GroundedChatResponse(
        status="success", answer="final answer", course_id="INT1339", kb_name="int1339-python",
        sources=[{"source_id": "c1"}],
        ai={"provider": "deepseek", "model": "deepseek-chat", "fallback_used": False},
    ))

    response = client(deeptutor, chat_service).post("/chat/grounded", json={
        "question": "What is a function?", "course_id": "INT1339", "kb_name": "int1339-python",
    })

    assert response.status_code == 200
    assert response.json() == {
        "status": "success", "answer": "final answer", "course_id": "INT1339", "kb_name": "int1339-python",
        "sources": [{"source_id": "c1"}],
        "ai": {"provider": "deepseek", "model": "deepseek-chat", "fallback_used": False},
    }
    assert deeptutor.kb_calls == [("INT1339", "int1339-python")]
    assert deeptutor.query_calls[0].kb_id == "int1339-python"
    sent_request = chat_service.chat.await_args.args[0]
    assert [item.text for item in sent_request.contexts] == ["retrieved text"]
    assert sent_request.course_id == "INT1339"
    assert sent_request.kb_name == "int1339-python"


def test_empty_sources_use_grounded_chat_safe_response_without_provider():
    deeptutor = FakeDeepTutor({"answer": "generated answer", "sources": []})
    orchestrator = MagicMock()
    orchestrator.generate = AsyncMock()
    response = client(deeptutor, GroundedChatService(orchestrator)).post(
        "/chat/grounded", json={"question": "Missing?", "course_id": "INT1339"}
    )

    assert response.status_code == 200
    assert response.json()["sources"] == []
    assert response.json()["ai"] == {"provider": "safe-fallback", "model": "local-safe", "fallback_used": True}
    orchestrator.generate.assert_not_awaited()


def test_grounded_chat_uses_the_course_mapped_kb_when_omitted():
    deeptutor = FakeDeepTutor({"sources": []})
    chat_service = MagicMock()
    chat_service.chat = AsyncMock(return_value=GroundedChatResponse(
        status="success", answer="safe", course_id="INT1339", kb_name="int1339-python",
        sources=[], ai={"provider": "safe-fallback", "model": "local-safe", "fallback_used": True},
    ))

    response = client(deeptutor, chat_service).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"}
    )

    assert response.status_code == 200
    assert deeptutor.query_calls[0].kb_id == "int1339-python"


def test_deeptutor_failure_does_not_call_ai():
    deeptutor = FakeDeepTutor({}, DeepTutorError("timeout", "DeepTutor command timed out.", status_code=504))
    chat_service = MagicMock()
    chat_service.chat = AsyncMock()

    response = client(deeptutor, chat_service).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"}
    )

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "timeout"
    chat_service.chat.assert_not_awaited()


def test_provider_failure_is_sanitized():
    deeptutor = FakeDeepTutor({"sources": []})
    chat_service = MagicMock()
    chat_service.chat = AsyncMock(side_effect=RuntimeError("D:/private/token=secret"))

    response = client(deeptutor, chat_service).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ai_provider_failure"
    assert "private" not in response.text.lower()
    assert "secret" not in response.text.lower()


@pytest.mark.parametrize("field", ["question", "course_id", "kb_name"])
def test_blank_request_rejected_before_retrieval(field):
    backend = FakeDeepTutor({"sources": []})
    chat = MagicMock()
    chat.chat = AsyncMock()
    request = {"question": "Question", "course_id": "INT1339", "kb_name": "int1339-python", field: " \t "}
    response = client(backend, chat).post("/chat/grounded", json=request)
    assert response.status_code == 422
    assert backend.query_calls == []
    chat.chat.assert_not_awaited()


def test_surrounding_whitespace_stripped():
    backend = FakeDeepTutor({"sources": []})
    orch = MagicMock()
    orch.generate = AsyncMock()
    response = client(backend, GroundedChatService(orch)).post("/chat/grounded", json={
        "question": " Question ", "course_id": " INT1339 ", "kb_name": " int1339-python ",
    })
    assert response.status_code == 200
    assert backend.kb_calls == [("INT1339", "int1339-python")]
    assert backend.query_calls[0].question == "Question"
    assert response.json()["course_id"] == "INT1339"
    orch.generate.assert_not_awaited()


@pytest.mark.parametrize("envelope", [
    None, [], "SECRET", {},
    {"course_id": "OTHER", "kb_id": "int1339-python", "result": {}},
    {"course_id": " ", "kb_id": "int1339-python", "result": {}},
    {"course_id": "INT1339", "kb_id": " ", "result": {}},
    {"course_id": "INT1339", "kb_id": None, "result": {}},
    *[{"course_id": "INT1339", "kb_id": "int1339-python", "result": result}
      for result in (None, [], "SECRET", {"sources": None}, {"sources": {}}, {"sources": "SECRET"})],
])
def test_invalid_envelope_never_reaches_ai(envelope):
    backend = FakeDeepTutor({})
    backend.query = MagicMock(return_value=envelope)
    chat = MagicMock()
    chat.chat = AsyncMock()
    response = client(backend, chat).post("/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_retrieval_response"
    assert "SECRET" not in response.text
    chat.chat.assert_not_awaited()


@pytest.mark.parametrize("location", ["source", "metadata"])
@pytest.mark.parametrize("key", ["course_id", "kb_id", "kb_name"])
def test_explicit_conflicting_source_identity_rejected(location, key):
    source = {"content": "SECRET_CONTEXT", "chunk_id": "c1"}
    if location == "source":
        source[key] = "SECRET_OTHER"
    else:
        source["metadata"] = {key: "SECRET_OTHER"}
    backend = FakeDeepTutor({"sources": [source]})
    chat = MagicMock()
    chat.chat = AsyncMock()
    response = client(backend, chat).post("/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_retrieval_response"
    assert "SECRET" not in response.text
    chat.chat.assert_not_awaited()


@pytest.mark.parametrize("code,status", [("kb_not_found", 404), ("kb_not_ready", 409), ("kb_course_mismatch", 422)])
def test_deeptutor_errors_preserved(code, status):
    chat = MagicMock()
    chat.chat = AsyncMock()
    response = client(FakeDeepTutor({}, DeepTutorError(code, "Safe message", status_code=status)), chat).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == status
    assert response.json()["detail"] == {"code": code, "message": "Safe message"}
    chat.chat.assert_not_awaited()


def test_unexpected_retrieval_failure_classification():
    backend = FakeDeepTutor({})
    backend.query = MagicMock(side_effect=RuntimeError("SECRET_EXCEPTION"))
    chat = MagicMock()
    chat.chat = AsyncMock()
    response = client(backend, chat).post("/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "retrieval_failure"
    assert "SECRET" not in response.text
    chat.chat.assert_not_awaited()


@pytest.mark.parametrize("bad", [None, {}, "SECRET", GroundedChatResponse(
    "success", None, "INT1339", "int1339-python", [], {}), GroundedChatResponse(
    "success", "OK", "INT1339", "int1339-python", [{"page": object()}],
    {"provider": "mock", "model": "mock", "fallback_used": False})])
def test_malformed_chat_result_sanitized(bad):
    chat = MagicMock()
    chat.chat = AsyncMock(return_value=bad)
    response = client(FakeDeepTutor({"sources": []}), chat).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ai_provider_failure"
    assert "SECRET" not in response.text


def test_provider_error_result_retains_shape_and_owned_sources():
    orch = MagicMock()
    orch.generate = AsyncMock(return_value=LLMResult(
        "error", "ollama", "qwen2.5:3b", "SECRET_PROVIDER_BODY", 1,
        error_code="SECRET_ERROR", fallback_used=True))
    backend = FakeDeepTutor({"answer": "SECRET_GENERATED", "content": "SECRET_GENERATED", "sources": [{
        "content": "Retrieved text", "chunk_id": "c1", "title": "notes.pdf",
        "course_id": "INT1339", "metadata": {"kb_name": "int1339-python"},
    }]})
    response = client(backend, GroundedChatService(orch)).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 200
    assert response.json() == {"status": "error", "answer": "", "course_id": "INT1339",
        "kb_name": "int1339-python", "sources": [{"source_id": "c1", "title": "notes.pdf"}],
        "ai": {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": True}}
    assert "SECRET" not in response.text
    assert "SECRET_GENERATED" not in orch.generate.call_args.kwargs["prompt"]


def test_raised_orchestrator_is_sanitized():
    orch = MagicMock()
    orch.generate = AsyncMock(side_effect=RuntimeError("SECRET_PROVIDER"))
    backend = FakeDeepTutor({"sources": [{"content": "Retrieved text"}]})
    response = client(backend, GroundedChatService(orch)).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ai_provider_failure"
    assert "SECRET" not in response.text


def test_model_claims_cannot_replace_structured_citations():
    orch = MagicMock()
    orch.generate = AsyncMock(return_value=LLMResult("success", "mock", "mock",
        '{"sources": [{"source_id": "fabricated"}], "answer": "text"}', 0))
    response = client(FakeDeepTutor({"sources": [{"content": "Retrieved", "chunk_id": "trusted"}]}),
                      GroundedChatService(orch)).post("/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.json()["sources"] == [{"source_id": "trusted"}]


@pytest.mark.parametrize("sources", [[], [None, {}, {"content": "  "}]])
def test_no_usable_context_does_not_call_provider(sources):
    orch = MagicMock()
    orch.generate = AsyncMock()
    response = client(FakeDeepTutor({"answer": "Generated", "sources": sources}), GroundedChatService(orch)).post(
        "/chat/grounded", json={"question": "Question", "course_id": "INT1339"})
    assert response.status_code == 200
    assert response.json()["answer"] and response.json()["sources"] == []
    orch.generate.assert_not_awaited()
