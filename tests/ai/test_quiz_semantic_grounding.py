import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai.grading_service import GradingService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.quiz_service import QuizService


PREFIX = "Complete the missing text in this exact excerpt from the verified source: "
CONTEXT = "Python is a programming language. Variables store values."


def question(evidence="Python is a programming language.", answer="programming language",
             *, text=None, correct_id="supported"):
    cloze = evidence.replace(answer, "____", 1)
    return {
        "question": text or PREFIX + cloze,
        "type": "mcq",
        "options": [
            {"id": correct_id, "text": answer},
            {"id": "distractor", "text": "database"},
        ],
        "correct_option_id": correct_id,
        "explanation": "The missing text is copied from the verified excerpt.",
        "grounding_evidence": evidence,
    }


def service_with(*questions):
    orchestrator = MagicMock(spec=AIOrchestrator)
    orchestrator.generate = AsyncMock(return_value=LLMResult(
        "success", "test", "test", json.dumps({"questions": list(questions)}), 0))
    return QuizService(orchestrator), orchestrator


async def generate(service, *, count=1, context=CONTEXT, source_metadata=None):
    return await service.generate_grounded_quiz(
        topic="Python", question_count=count, difficulty="easy",
        question_types=["mcq"], retrieved_context=context,
        source_metadata=source_metadata, client_facing=False,
    )


@pytest.mark.asyncio
async def test_exact_source_cloze_and_key_are_accepted_but_remain_private():
    service, _ = service_with(question())
    internal = await generate(service)
    assert internal["questions"][0]["grounding_evidence"] == "Python is a programming language."
    public = service.to_public_result(internal)
    encoded = json.dumps(public)
    assert "correct_option_id" not in encoded
    assert "grounding_evidence" not in encoded
    assert "explanation" not in encoded


@pytest.mark.asyncio
async def test_structurally_valid_question_outside_verified_context_fails_closed():
    unsupported = question("The moon is made of cheese.", "cheese")
    service, _ = service_with(unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_mixed_quiz_with_one_unsupported_question_is_rejected_as_a_unit():
    unsupported = question("The moon is made of cheese.", "cheese")
    service, _ = service_with(question(), unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, count=2)


@pytest.mark.asyncio
async def test_freeform_question_cannot_borrow_an_unrelated_valid_quote():
    candidate = question(text="Which database is implemented by Python?")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_correct_option_must_be_the_unique_missing_source_span():
    candidate = question(answer="high-level programming language")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_overlapping_answer_occurrences_are_ambiguous_and_rejected():
    candidate = question("aaa fact", "aa")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, context="aaa fact")


@pytest.mark.asyncio
async def test_untrusted_cross_course_metadata_cannot_expand_grounding_context():
    unsupported = question("Databases use structured query language.", "structured query language")
    service, _ = service_with(unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, source_metadata=[{
            "course_id": "OTHER", "untrusted_excerpt": unsupported["grounding_evidence"],
        }])


def test_existing_persisted_quiz_without_grounding_field_keeps_historical_grading():
    stored = [{
        "question_id": "historical-question", "question": "Historical question",
        "type": "mcq", "options": [
            {"id": "stored-correct", "text": "private correct text"},
            {"id": "stored-wrong", "text": "private wrong text"},
        ],
        "correct_option_id": "stored-correct", "explanation": "Historical rationale",
    }]
    result = GradingService().grade(stored, [{
        "question_id": "historical-question", "selected_option_id": "stored-wrong",
        "correct": True, "score": 100,
    }])
    assert result["score_percent"] == 0
    assert result["correct_count"] == 0
