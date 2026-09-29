import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=AIOrchestrator)
    valid_json = json.dumps({
        "flashcards": [
            {
                "front_text": "Python là gì?",
                "back_text": "Ngôn ngữ lập trình bậc cao",
                "topic": "Programming",
                "difficulty": "easy"
            }
        ]
    })
    orch.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock-model", content=valid_json, latency_ms=10.0
    ))
    return orch

@pytest.mark.asyncio
async def test_valid_flashcards(mock_orchestrator):
    service = FlashcardService(mock_orchestrator)
    result = await service.generate_flashcards("Tạo flashcard")
    assert "flashcards" in result
    card = result["flashcards"][0]
    assert card["front_text"] == "Python là gì?"
    assert card["back_text"] == "Ngôn ngữ lập trình bậc cao"
    assert card["topic"] == "Programming"

@pytest.mark.asyncio
async def test_malformed_json(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content="Not a json", latency_ms=5.0
    ))
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_FLASHCARD_SCHEMA"):
        await service.generate_flashcards("Test")

@pytest.mark.asyncio
async def test_missing_flashcards_list(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps({"items": []}), latency_ms=5.0
    ))
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_FLASHCARD_SCHEMA"):
        await service.generate_flashcards("Test")

@pytest.mark.asyncio
async def test_front_empty_whitespace(mock_orchestrator):
    bad_data = {
        "flashcards": [
            {"front_text": "   ", "back_text": "Valid back"}
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_FLASHCARD_SCHEMA"):
        await service.generate_flashcards("Test")

@pytest.mark.asyncio
async def test_back_empty_whitespace(mock_orchestrator):
    bad_data = {
        "flashcards": [
            {"front_text": "Valid front", "back_text": ""}
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_FLASHCARD_SCHEMA"):
        await service.generate_flashcards("Test")

@pytest.mark.asyncio
async def test_malformed_card_mixed_with_valid(mock_orchestrator):
    mixed_data = {
        "flashcards": [
            {"front_text": "Valid", "back_text": "Valid back"},
            {"front_text": "", "back_text": "Invalid front"}
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(mixed_data), latency_ms=5.0
    ))
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_FLASHCARD_SCHEMA"):
        await service.generate_flashcards("Test")

@pytest.mark.asyncio
async def test_source_metadata_preservation(mock_orchestrator):
    service = FlashcardService(mock_orchestrator)
    meta = {"source_id": "doc_123", "kb_name": "CourseKB"}
    result = await service.generate_flashcards("Test", source_metadata=meta)
    assert result["flashcards"][0]["source_metadata"] == meta
