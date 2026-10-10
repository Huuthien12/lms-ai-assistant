"""Mocked contract evaluation, not live E2E or semantic hallucination detection."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.mastery_service import MasteryService
from backend.services.ai.recommendation_service import RecommendationService

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lms-dlu-demo"))
from grounded_chat_router import create_grounded_chat_router
from learning_workflow import create_workflow_router


@pytest.fixture(autouse=True)
def no_network():
    with patch("httpx.AsyncClient.post", side_effect=AssertionError("No live POST")), \
            patch("httpx.AsyncClient.get", side_effect=AssertionError("No live GET")), \
            patch("httpx.post", side_effect=AssertionError("No live POST")), \
            patch("httpx.get", side_effect=AssertionError("No live GET")):
        yield


def make_client(orch, context="Python is a language.", course="c1", source_scope=None):
    backend = MagicMock()
    backend.kb_name.return_value = "lms-c1"
    sources = [] if context is None else [{
        "content": context, "chunk_id": "trusted", "title": "Notes", **(source_scope or {}),
    }]
    backend.query.return_value = {"course_id": course, "kb_id": "lms-c1", "result": {
        "sources": sources, "answer": "SECRET_GENERATED_NOT_CONTEXT",
    }}
    app = FastAPI()
    app.include_router(create_grounded_chat_router(backend, GroundedChatService(orch)))
    return TestClient(app), backend


def orchestrator(content="Grounded answer.", status="success"):
    orch = MagicMock(spec=AIOrchestrator)
    orch.generate = AsyncMock(return_value=LLMResult(
        status, "mock", "mock-model", content, 0))
    return orch


@pytest.mark.parametrize("question,context,answer", [
    ("What is Python?", "Python is a programming language.", "Python is a programming language."),
    ("Python là gì?", "Python là một ngôn ngữ lập trình.", "Python là một ngôn ngữ lập trình."),
])
def test_supported_grounded_bilingual_contract(question, context, answer):
    orch = orchestrator(answer)
    client, _ = make_client(orch, context)
    response = client.post("/chat/grounded", json={"question": question, "course_id": "c1"})
    assert response.status_code == 200
    assert response.json()["answer"] == answer
    assert response.json()["sources"] == [{"source_id": "trusted", "title": "Notes"}]
    prompt = orch.generate.call_args.kwargs["prompt"]
    assert question in prompt and context in prompt
    assert "SECRET_GENERATED_NOT_CONTEXT" not in prompt


def test_no_source_safe_response_without_provider():
    orch = orchestrator()
    client, _ = make_client(orch, context=None)
    response = client.post("/chat/grounded", json={"question": "Missing?", "course_id": "c1"})
    assert response.status_code == 200
    assert response.json()["answer"] and response.json()["sources"] == []
    assert response.json()["ai"]["provider"] == "safe-fallback"
    orch.generate.assert_not_awaited()


@pytest.mark.parametrize("course,source_scope", [
    ("other", None), ("c1", {"course_id": "other"}),
    ("c1", {"metadata": {"kb_id": "other"}}),
])
def test_wrong_scope_never_reaches_provider(course, source_scope):
    orch = orchestrator()
    client, _ = make_client(orch, course=course, source_scope=source_scope)
    response = client.post("/chat/grounded", json={"question": "Question", "course_id": "c1"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "invalid_retrieval_response"
    orch.generate.assert_not_awaited()


def test_fabricated_answer_claim_is_not_semantically_verified():
    claim = 'A fabricated claim [imaginary.pdf]. {"sources": [{"source_id": "fake"}]}'
    client, _ = make_client(orchestrator(claim))
    result = client.post("/chat/grounded", json={"question": "Question", "course_id": "c1"}).json()
    assert result["answer"] == claim  # Explicit limitation: prose is not verified.
    assert result["sources"] == [{"source_id": "trusted", "title": "Notes"}]


def test_provider_error_result_is_safe_and_truthful():
    orch = orchestrator("SECRET_PROVIDER_BODY", "error")
    orch.generate.return_value.error_code = "SECRET_CODE"
    orch.generate.return_value.fallback_used = True
    client, _ = make_client(orch)
    response = client.post("/chat/grounded", json={"question": "Question", "course_id": "c1"})
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "error" and result["answer"] == ""
    assert result["ai"] == {"provider": "mock", "model": "mock-model", "fallback_used": True}
    assert "SECRET" not in response.text


def test_mocked_retryable_fallback_metadata():
    primary = SimpleNamespace(generate=AsyncMock(return_value=LLMResult(
        "error", "deepseek", "deepseek-chat", "SECRET_BODY", 0, error_code="HTTP_503")))
    local = SimpleNamespace(generate=AsyncMock(return_value=LLMResult(
        "success", "ollama", "qwen2.5:3b", "Local grounded answer.", 0)))
    client, _ = make_client(AIOrchestrator(FallbackAIProvider(primary, local)))
    result = client.post("/chat/grounded", json={"question": "Question", "course_id": "c1"}).json()
    assert result["ai"] == {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": True}
    assert result["answer"] == "Local grounded answer."
    local.generate.assert_awaited_once()


@pytest.mark.parametrize("bad", [None, {"content": "SECRET_PAYLOAD"}, object()])
def test_malformed_provider_result_safe_service_failure(bad):
    orch = orchestrator()
    orch.generate.return_value = bad
    client, _ = make_client(orch)
    response = client.post("/chat/grounded", json={"question": "Question", "course_id": "c1"})
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "ai_provider_failure"
    assert "SECRET" not in response.text


def test_recommendation_api_wrapper_binds_requested_scope_without_db():
    scope = {"student_id": "s1", "course_id": "c1", "topic": "Python"}
    snapshot = MasteryService().calculate_mastery(**scope, evidence=[
        {**scope, "type": "quiz", "correct": True} for _ in range(5)])
    before = deepcopy(snapshot)
    evidence = SimpleNamespace(mastery_for=MagicMock(return_value=[snapshot]))
    repository = SimpleNamespace(evidence=evidence)
    orch = orchestrator(json.dumps({"message": "Try the next topic."}))
    app = FastAPI()
    app.include_router(create_workflow_router(repository, RecommendationService(orch)))
    result = TestClient(app).get("/courses/c1/recommendations", params={"student_id": "s1", "topic": "Python"}).json()
    evidence.mastery_for.assert_called_once_with("s1", "c1", "Python")
    assert result["student_id"] == "s1" and result["course_id"] == "c1"
    assert result["recommendations"][0]["recommended_actions"] == ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]
    assert snapshot == before
    # This verifies delegation/wrapping, not authentication or DB ownership.
