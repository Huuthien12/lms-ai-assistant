import ast
from copy import deepcopy
import inspect
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.recommendation_service import RecommendationService


def mastery(**changes):
    return {"topic": "Python", "mastery_score": 42.0, "confidence": "MEDIUM",
            "evidence_count": 7, **changes}


@pytest.fixture
def orch():
    mock = MagicMock(spec=AIOrchestrator)
    mock.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="PRIVATE_PROVIDER", model="PRIVATE_MODEL",
        content=json.dumps({"message": "Review the topic."}), latency_ms=1, error_code="PRIVATE_CODE"))
    return mock


@pytest.mark.asyncio
@pytest.mark.parametrize("score,level,actions", [
    (0, "WEAK", ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]),
    (49.99, "WEAK", ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]),
    (50, "DEVELOPING", ["REVIEW_TOPIC", "MEDIUM_QUIZ"]),
    (69.99, "DEVELOPING", ["REVIEW_TOPIC", "MEDIUM_QUIZ"]),
    (70, "GOOD", ["MEDIUM_QUIZ", "HARD_QUIZ"]),
    (84.99, "GOOD", ["MEDIUM_QUIZ", "HARD_QUIZ"]),
    (85, "MASTERED", ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]),
    (100, "MASTERED", ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]),
])
async def test_rules(orch, score, level, actions):
    result = await RecommendationService(orch).get_recommendations(mastery(mastery_score=score), [])
    assert result == {
        "status": "success", "topic": "Python", "mastery_score": score, "level": level,
        "confidence": "MEDIUM", "evidence_count": 7, "recommended_actions": actions,
        "deadline": None, "message": "Review the topic.", "message_source": "llm",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"evidence_count": 0}, {"evidence_count": 1}, {"confidence": "LOW"},
    {"confidence": "LOW", "confidence_level": "HIGH"},
])
async def test_insufficient_q5_confidence(orch, changes):
    result = await RecommendationService(orch).get_recommendations(mastery(mastery_score=99, **changes), [])
    assert result["level"] == "INSUFFICIENT_EVIDENCE"
    assert result["recommended_actions"] == ["REVIEW_TOPIC", "EASY_QUIZ"]


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline", [None, "2026-10-15"])
async def test_llm_cannot_override_rule_fields(orch, deadline):
    fake = {"mastery_score": 100, "level": "MASTERED", "confidence": "HIGH",
            "evidence_count": 999, "recommended_actions": ["FAKE_ACTION"],
            "deadline": "2099-01-01", "available_courses_or_topics": ["Fake course"]}
    orch.generate.return_value.content = json.dumps(fake)
    service = RecommendationService(orch)
    result = await service.get_recommendations(mastery(), ["Next topic"], deadline)
    expected = service._evaluate_rule_first(mastery(), deadline)
    assert {key: result[key] for key in expected} == expected
    assert result["message"] == "Recommended actions: REVIEW_TOPIC, GENERATE_FLASHCARDS, EASY_QUIZ."
    assert result["message_source"] == "rule-engine"
    assert "FAKE_ACTION" not in str(result)
    assert "2099-01-01" not in str(result)
    assert "Fake course" not in str(result)
    prompt = json.loads(orch.generate.call_args.kwargs["prompt"])
    assert prompt == {"recommendation": expected, "available_courses_or_topics": ["Next topic"]}
    instructions = orch.generate.call_args.kwargs["system_prompt"]
    for term in ("mastery", "confidence", "evidence_count", "recommended_actions",
                 "add/remove", "deadline", "courses/topics"):
        assert term in instructions
    assert "PRIVATE" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    'SECRET_MALFORMED_JSON',
    '{"message": "SECRET_INCOMPLETE"',
    '```json\n{"message": "SECRET_FENCED"}\n```',
    json.dumps([{"message": "SECRET_ARRAY"}]),
    json.dumps("SECRET_STRING"),
    'null', 'true', '42', '{}',
    json.dumps({"message": ""}),
    json.dumps({"message": "  "}),
    json.dumps({"message": None}),
    json.dumps({"message": 1}),
    json.dumps({"message": {"secret": "SECRET_OBJECT"}}),
    *[json.dumps({"message": "SECRET_EXTRA_KEY", key: value})
      for key, value in [
          ("mastery_score", 100), ("confidence", "HIGH"), ("evidence_count", 999),
          ("recommended_actions", ["FAKE_ACTION"]), ("deadline", "2099-01-01"),
          ("available_courses_or_topics", ["Fake course"]), ("extra", "SECRET"),
      ]],
])
async def test_invalid_wording_never_leaks(orch, content, caplog):
    orch.generate.return_value.content = content
    service = RecommendationService(orch)
    result = await service.get_recommendations(mastery(), ["Next topic"], "2026-10-15")
    expected = service._evaluate_rule_first(mastery(), "2026-10-15")
    assert {key: result[key] for key in expected} == expected
    assert result["message_source"] == "rule-engine"
    assert result["message"] == "Recommended actions: REVIEW_TOPIC, GENERATE_FLASHCARDS, EASY_QUIZ."
    assert "SECRET" not in str(result) + caplog.text
    assert "FAKE_ACTION" not in str(result)


@pytest.mark.asyncio
async def test_valid_message_only_contract_and_prompt(orch):
    result = await RecommendationService(orch).get_recommendations(mastery(), [])
    assert result["message"] == "Review the topic."
    assert result["message_source"] == "llm"
    instructions = orch.generate.call_args.kwargs["system_prompt"]
    for phrase in (
        "Explain only the supplied recommended_actions",
        "Do not state or repeat mastery_score, confidence or evidence_count",
        "Do not change recommended_actions or add/remove actions",
        "Do not state or invent a deadline",
        "Do not mention or invent unavailable courses/topics",
        'Return strict JSON with only "message": "..."',
    ):
        assert phrase in instructions


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["status", "exception", "blank", "nontext", "malformed"])
async def test_safe_fallback(orch, failure, caplog):
    if failure == "status":
        orch.generate.return_value.status = "error"
        orch.generate.return_value.content = "SECRET_PROVIDER_ERROR"
    elif failure == "exception":
        orch.generate.side_effect = RuntimeError("SECRET_EXCEPTION")
    elif failure == "blank":
        orch.generate.return_value.content = "  "
    elif failure == "nontext":
        orch.generate.return_value.content = {"secret": "SECRET"}
    else:
        orch.generate.return_value = None
    result = await RecommendationService(orch).get_recommendations(mastery(), [])
    expected = RecommendationService(orch)._evaluate_rule_first(mastery())
    assert {key: result[key] for key in expected} == expected
    assert result["message_source"] == "rule-engine"
    assert result["message"] == "Recommended actions: REVIEW_TOPIC, GENERATE_FLASHCARDS, EASY_QUIZ."
    assert "SECRET" not in str(result) + caplog.text
    assert "PRIVATE" not in str(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, [], "SECRET", {}, 1])
async def test_invalid_mastery_structure(orch, bad):
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT"):
        await RecommendationService(orch).get_recommendations(bad, [])
    orch.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("topic", ""), ("topic", " "), ("topic", None), ("topic", 1),
    ("mastery_score", -1), ("mastery_score", 101), ("mastery_score", float("nan")),
    ("mastery_score", float("inf")), ("mastery_score", float("-inf")),
    ("mastery_score", True), ("mastery_score", False), ("mastery_score", None),
    ("mastery_score", "SECRET"), ("mastery_score", 10**1000),
    ("evidence_count", -1), ("evidence_count", True), ("evidence_count", False),
    ("evidence_count", 2.0), ("evidence_count", "2"), ("evidence_count", None),
    ("confidence", "low"), ("confidence", "UNKNOWN"), ("confidence", None), ("confidence", []),
])
async def test_invalid_mastery_fields(orch, field, value):
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT") as error:
        await RecommendationService(orch).get_recommendations(mastery(**{field: value}), [])
    assert "SECRET" not in str(error.value)
    orch.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["topic", "mastery_score", "evidence_count", "confidence"])
async def test_required_fields(orch, field):
    data = mastery()
    del data[field]
    data["confidence_level"] = "HIGH"
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT"):
        await RecommendationService(orch).get_recommendations(data, [])
    orch.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("available", [None, {}, (), "Python", [None], [" "], [1]])
async def test_invalid_available_topics(orch, available):
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT"):
        await RecommendationService(orch).get_recommendations(mastery(), available)
    orch.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline", ["", "  ", 1, True, [], {}])
async def test_invalid_deadline(orch, deadline):
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT"):
        await RecommendationService(orch).get_recommendations(mastery(), [], deadline)
    orch.generate.assert_not_called()


@pytest.mark.asyncio
async def test_inputs_preserved_and_options_forwarded(orch):
    data = mastery(level="UNTRUSTED", components={"nested": [1, 2]})
    available = ["Next topic"]
    before = deepcopy((data, available))
    result = await RecommendationService(orch).get_recommendations(data, available, "2026-10-15", temperature=0)
    assert (data, available) == before
    assert result["deadline"] == "2026-10-15"
    assert result["level"] == "WEAK"
    assert orch.generate.call_args.kwargs["temperature"] == 0
    orch.generate.assert_awaited_once()


def test_only_orchestrator_ai_dependency():
    import backend.services.ai.recommendation_service as module

    tree = ast.parse(inspect.getsource(module))
    ai_imports = [node.module for node in ast.walk(tree)
                  if isinstance(node, ast.ImportFrom) and node.module.startswith("backend.")]
    assert ai_imports == ["backend.services.ai.orchestrator"]
