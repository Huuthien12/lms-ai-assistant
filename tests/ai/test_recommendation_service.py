import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.recommendation_service import RecommendationService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=AIOrchestrator)
    orch.generate = AsyncMock(return_value=LLMResult(
        status="success",
        provider="mock",
        model="mock-model",
        content="Đề xuất học tập cá nhân hóa.",
        latency_ms=10.0
    ))
    return orch

@pytest.mark.asyncio
async def test_rec_01_weak_topic(mock_orchestrator):
    service = RecommendationService(mock_orchestrator)
    mastery = {
        "student_id": "s1",
        "course_id": "c1",
        "topic": "Python Basics",
        "mastery_score": 40.0,
        "mastery_level": "WEAK",
        "confidence_level": "HIGH",
        "evidence_count": 5,
        "last_updated_at": "2026-09-29"
    }
    res = await service.get_recommendations(mastery, ["Advanced Python"])
    rule_eval = service._evaluate_rule_first(mastery)
    assert rule_eval["recommended_actions"] == ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]
    assert res.status == "success"

@pytest.mark.asyncio
async def test_rec_02_mastered_topic(mock_orchestrator):
    service = RecommendationService(mock_orchestrator)
    mastery = {
        "student_id": "s1",
        "course_id": "c1",
        "topic": "Python Basics",
        "mastery_score": 90.0,
        "mastery_level": "MASTERED",
        "confidence_level": "HIGH",
        "evidence_count": 6,
        "last_updated_at": "2026-09-29"
    }
    rule_eval = service._evaluate_rule_first(mastery)
    assert "CONTINUE_NEXT_TOPIC" in rule_eval["recommended_actions"] or "HARD_QUIZ" in rule_eval["recommended_actions"]
    assert rule_eval["status_note"] != "WEAK"

@pytest.mark.asyncio
async def test_boundary_scores(mock_orchestrator):
    service = RecommendationService(mock_orchestrator)
    scores = [
        (49.0, ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]),
        (50.0, ["REVIEW_TOPIC", "MEDIUM_QUIZ"]),
        (69.0, ["REVIEW_TOPIC", "MEDIUM_QUIZ"]),
        (70.0, ["MEDIUM_QUIZ", "HARD_QUIZ"]),
        (84.0, ["MEDIUM_QUIZ", "HARD_QUIZ"]),
        (85.0, ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"])
    ]
    for score, expected_actions in scores:
        mastery = {
            "student_id": "s1", "course_id": "c1", "topic": "Test",
            "mastery_score": score, "confidence_level": "HIGH", "evidence_count": 5
        }
        eval_res = service._evaluate_rule_first(mastery)
        assert eval_res["recommended_actions"] == expected_actions

@pytest.mark.asyncio
async def test_rec_03_insufficient_evidence(mock_orchestrator):
    service = RecommendationService(mock_orchestrator)
    mastery = {
        "student_id": "s1", "course_id": "c1", "topic": "Test",
        "mastery_score": 30.0, "confidence_level": "LOW", "evidence_count": 1
    }
    eval_res = service._evaluate_rule_first(mastery)
    assert eval_res["insufficient_evidence"] is True
    assert eval_res["status_note"] == "INSUFFICIENT_EVIDENCE"

@pytest.mark.asyncio
async def test_rec_04_llm_failure_fallback(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="mock", model="mock", content="Error", error_code="API_ERROR", latency_ms=0.0
    ))
    service = RecommendationService(mock_orchestrator)
    mastery = {
        "student_id": "s1", "course_id": "c1", "topic": "Test",
        "mastery_score": 40.0, "confidence_level": "HIGH", "evidence_count": 5
    }
    res = await service.get_recommendations(mastery, ["Topic 2"])
    assert res.status == "success"
    assert "REVIEW_TOPIC" in res.content

@pytest.mark.asyncio
async def test_rec_05_deadline_handling(mock_orchestrator):
    service = RecommendationService(mock_orchestrator)
    mastery = {
        "student_id": "s1", "course_id": "c1", "topic": "Test",
        "mastery_score": 60.0, "confidence_level": "HIGH", "evidence_count": 3
    }
    eval_no_dl = service._evaluate_rule_first(mastery)
    assert eval_no_dl["deadline"] is None

    eval_with_dl = service._evaluate_rule_first(mastery, deadline="2026-10-15")
    assert eval_with_dl["deadline"] == "2026-10-15"
