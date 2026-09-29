import pytest
import json
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.quiz_service import QuizService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=AIOrchestrator)
    valid_quiz_json = json.dumps({
        "questions": [
            {
                "question": "Python là gì?",
                "type": "mcq",
                "options": [
                    {"id": "A", "text": "Ngôn ngữ lập trình"},
                    {"id": "B", "text": "Loài rắn"}
                ],
                "correct_option_id": "A",
                "explanation": "Python là ngôn ngữ lập trình bậc cao."
            }
        ]
    })
    orch.generate = AsyncMock(return_value=LLMResult(
        status="success",
        provider="mock",
        model="mock-model",
        content=valid_quiz_json,
        latency_ms=10.0
    ))
    return orch

@pytest.mark.asyncio
async def test_valid_internal_quiz(mock_orchestrator):
    service = QuizService(mock_orchestrator)
    result = await service.generate_quiz("Tạo quiz Python", client_facing=False)
    assert "questions" in result
    q = result["questions"][0]
    assert q["correct_option_id"] == "A"
    assert "explanation" in q
    assert q["explanation"] != ""

@pytest.mark.asyncio
async def test_valid_client_facing_quiz(mock_orchestrator):
    service = QuizService(mock_orchestrator)
    result = await service.generate_quiz("Tạo quiz Python", client_facing=True)
    assert "questions" in result
    q = result["questions"][0]
    assert "question" in q
    assert "options" in q
    # Kiểm tra tuyệt đối không chứa correct_answer, correct_option_id, explanation
    assert "correct_answer" not in q
    assert "correct_option_id" not in q
    assert "explanation" not in q

@pytest.mark.asyncio
async def test_malformed_json(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content="Not a json string", latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test malformed")

@pytest.mark.asyncio
async def test_missing_empty_questions(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps({"questions": []}), latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test empty questions")

@pytest.mark.asyncio
async def test_invalid_options_structure(mock_orchestrator):
    bad_data = {
        "questions": [
            {
                "question": "Hỏi?",
                "type": "mcq",
                "options": [{"id": "A"}], # thiếu text
                "correct_option_id": "A"
            }
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test bad option")

@pytest.mark.asyncio
async def test_duplicate_option_ids(mock_orchestrator):
    bad_data = {
        "questions": [
            {
                "question": "Hỏi?",
                "type": "mcq",
                "options": [
                    {"id": "A", "text": "Opt 1"},
                    {"id": "A", "text": "Opt 2"}
                ],
                "correct_option_id": "A"
            }
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test duplicate IDs")

@pytest.mark.asyncio
async def test_correct_answer_nonexistent_option(mock_orchestrator):
    bad_data = {
        "questions": [
            {
                "question": "Hỏi?",
                "type": "mcq",
                "options": [
                    {"id": "A", "text": "Opt 1"}
                ],
                "correct_option_id": "B" # Không tồn tại
            }
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test nonexistent option")

@pytest.mark.asyncio
async def test_empty_question_text(mock_orchestrator):
    bad_data = {
        "questions": [
            {
                "question": "   ",
                "type": "mcq",
                "options": [{"id": "A", "text": "Opt"}],
                "correct_option_id": "A"
            }
        ]
    }
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=json.dumps(bad_data), latency_ms=5.0
    ))
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Test empty question text")
