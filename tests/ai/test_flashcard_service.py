import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.flashcard_service import FlashcardService

@pytest.mark.asyncio
async def test_flashcard_generation_success():
    mock_orchestrator = AsyncMock(spec=AIOrchestrator)
    mock_orchestrator.generate.return_value = LLMResult(
        status="success",
        provider="deepseek",
        model="chat",
        content='{"flashcards": [{"front": "OOP", "back": "Object-Oriented Programming"}]}',
        latency_ms=130
    )

    flashcard_service = FlashcardService(orchestrator=mock_orchestrator)
    result = await flashcard_service.generate_flashcards(topic_or_text="Python OOP", count=1)

    assert result.status == "success"
    assert "flashcards" in result.content
    mock_orchestrator.generate.assert_awaited_once()