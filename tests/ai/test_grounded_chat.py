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
async def test_response_allows_only_safe_public_source_citations(mock_orchestrator):
    item = RetrievedContextItem(
        text="Source content.",
        source_id="doc_123",
        title="LMS document",
        score=0.95,
        metadata={
            "page": 3,
            "source": "D:\\runtime\\document.pdf",
            "path": "/tmp/document.pdf",
            "token": "secret",
        },
    )
    request = GroundedChatRequest(query="Test?", contexts=[item], course_id="course_99", kb_name="kb_test")

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert response.sources == [{
        "source_id": "doc_123",
        "title": "LMS document",
        "score": 0.95,
        "page": 3,
    }]
    assert "runtime" not in str(response.sources)
    assert "tmp/document" not in str(response.sources)
    assert "secret" not in str(response.sources)


@pytest.mark.asyncio
async def test_response_does_not_fabricate_missing_source_fields(mock_orchestrator):
    request = GroundedChatRequest(query="Test?", contexts=[RetrievedContextItem(text="Only context text.")])

    response = await GroundedChatService(mock_orchestrator).chat(request)

    assert response.sources == [{}]
    assert not {"source_id", "title", "score", "page"} & response.sources[0].keys()


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


@pytest.mark.asyncio
async def test_provider_error_content_is_not_public(mock_orchestrator):
    mock_orchestrator.generate.return_value = LLMResult(
        "error", "ollama", "qwen2.5:3b", "SECRET_BODY", 0,
        error_code="SECRET_ERROR", fallback_used=True)
    request = GroundedChatRequest("Question", [RetrievedContextItem(text="Context", source_id="trusted")],
                                  "INT1339", "int1339-python")
    result = await GroundedChatService(mock_orchestrator).chat(request)
    assert result.status == "error" and result.answer == ""
    assert result.sources == [{"source_id": "trusted"}]
    assert result.ai == {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": True}
    assert "SECRET" not in str(result)
