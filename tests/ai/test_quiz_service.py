import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.quiz_service import QuizGenerationService

@pytest.mark.asyncio
async def test_quiz_generation_success():
    mock_orchestrator = AsyncMock(spec=AIOrchestrator)
    mock_orchestrator.generate.return_value = LLMResult(
        status="success",
        provider="deepseek",
        model="chat",
        content='{"questions": [{"question": "Q1?", "options": ["A", "B", "C", "D"], "correct_answer": "A", "explanation": "Exp"}]}',
        latency_ms=150
    )

    quiz_service = QuizGenerationService(orchestrator=mock_orchestrator)
    result = await quiz_service.generate_quiz(topic="Python Basics", num_questions=1)

    assert result.status == "success"
    assert "questions" in result.content
    mock_orchestrator.generate.assert_awaited_once()