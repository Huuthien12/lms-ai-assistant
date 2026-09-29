import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.ai.grounded_chat import (
    GroundedChatRequest,
    GroundedChatResponse,
    GroundedChatService,
    RetrievedContextItem,
)
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult


@pytest.fixture
def mock_orchestrator():
    orchestrator = MagicMock(spec=AIOrchestrator)
    orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success",
        provider="mock",
        model="mock-model",
        content="Grounded answer.",
        latency_ms=15.0,
        fallback_used=True,
    ))
    return orchestrator


@pytest.mark.asyncio
async def test_normal_response_preserves_result_and_request_metadata(mock_orchestrator):
    request = GroundedChatRequest(
        query="What is Python?",
        contexts=[RetrievedContextItem(text="Python is a programming language.")],
        course_id="c1",
        kb_name="python_kb",
    )

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert isinstance(response, GroundedChatResponse)
    assert response.status == "success"
    assert response.answer == "Grounded answer."
    assert response.course_id == "c1"
    assert response.kb_name == "python_kb"
    assert response.ai == {"provider": "mock", "model": "mock-model", "fallback_used": True}
    mock_orchestrator.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_response_preserves_real_source_metadata(mock_orchestrator):
    item = RetrievedContextItem(
        text="Source content.",
        source_id="doc_123",
        title="LMS document",
        url="https://lms.example.test/doc",
        score=0.95,
        metadata={"page": 3},
    )
    request = GroundedChatRequest(query="Test?", contexts=[item], course_id="course_99", kb_name="kb_test")

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert response.sources == [{
        "source_id": "doc_123",
        "title": "LMS document",
        "url": "https://lms.example.test/doc",
        "score": 0.95,
        "metadata": {"page": 3},
    }]


@pytest.mark.asyncio
async def test_response_does_not_fabricate_missing_source_fields(mock_orchestrator):
    request = GroundedChatRequest(query="Test?", contexts=[RetrievedContextItem(text="Only context text.")])

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert response.sources == [{}]
    assert not {"source_id", "title", "url"} & response.sources[0].keys()


@pytest.mark.asyncio
async def test_empty_context_returns_safe_response_without_provider(mock_orchestrator):
    request = GroundedChatRequest(query="No context", contexts=[], course_id="MATH101", kb_name="math_kb")

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert isinstance(response, GroundedChatResponse)
    assert response.status == "success"
    assert response.answer
    assert response.course_id == "MATH101"
    assert response.kb_name == "math_kb"
    assert response.sources == []
    assert response.ai == {"provider": "safe-fallback", "model": "local-safe", "fallback_used": True}
    mock_orchestrator.generate.assert_not_awaited()
