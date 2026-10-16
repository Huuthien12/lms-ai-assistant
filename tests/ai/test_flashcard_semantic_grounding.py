import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult


CONTEXT = "Python uses indentation to define blocks."
EVIDENCE = CONTEXT
ANSWER = "indentation"


def grounded_card(**overrides):
    card = {
        "front_text": (
            FlashcardService.GROUNDING_FRONT_PREFIX
            + "Python uses ____ to define blocks."
        ),
        "back_text": ANSWER,
        "topic": "Python",
        "difficulty": "easy",
        "grounding_evidence": EVIDENCE,
    }
    card.update(overrides)
    return card


def service_for(*cards):
    orchestrator = MagicMock(spec=AIOrchestrator)
    orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="success",
        provider="mock",
        model="mock-model",
        content=json.dumps({"flashcards": list(cards)}),
        latency_ms=1.0,
    ))
    return FlashcardService(orchestrator), orchestrator


async def generate(service, *, count=1, context=CONTEXT, source_metadata=None):
    return await service.generate_grounded_flashcards(
        topic="Python",
        count=count,
        difficulty="easy",
        retrieved_context=context,
        source_metadata=source_metadata or {
            "course_id": "INT1339", "source_id": "lecture-1"
        },
    )


@pytest.mark.asyncio
async def test_supported_extract_is_accepted_and_retains_private_evidence():
    service, _ = service_for(grounded_card())

    result = await generate(service)

    assert result["flashcards"][0]["grounding_evidence"] == EVIDENCE


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"grounding_evidence": "Java uses braces to define blocks."},
    {"front_text": "What does Python use to define blocks?"},
    {"back_text": "decorators"},
    {"grounding_evidence": "indentation indentation defines blocks.",
     "front_text": FlashcardService.GROUNDING_FRONT_PREFIX + "____ indentation defines blocks."},
])
async def test_unsupported_or_ambiguous_card_is_rejected(mutation):
    service, _ = service_for(grounded_card(**mutation))

    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await generate(service)


@pytest.mark.asyncio
async def test_mixed_batch_fails_closed_without_partial_result():
    second = grounded_card(
        front_text=FlashcardService.GROUNDING_FRONT_PREFIX + "Python uses ____.",
        back_text="braces",
        grounding_evidence="Python uses braces.",
    )
    service, _ = service_for(grounded_card(), second)

    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await generate(service, count=2)


@pytest.mark.asyncio
async def test_repeated_answer_span_is_rejected_as_ambiguous():
    context = "Python uses indentation indentation to define blocks."
    service, _ = service_for(grounded_card(
        front_text=(FlashcardService.GROUNDING_FRONT_PREFIX
                    + "Python uses ____ indentation to define blocks."),
        grounding_evidence=context,
    ))

    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await generate(service, context=context)


@pytest.mark.asyncio
async def test_source_metadata_cannot_extend_verified_grounding_context():
    service, _ = service_for(grounded_card(
        front_text=FlashcardService.GROUNDING_FRONT_PREFIX + "Java uses ____.",
        back_text="braces",
        grounding_evidence="Java uses braces.",
    ))

    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await generate(service, source_metadata={
            "course_id": "OTHER",
            "source_id": "foreign",
            "content": "Java uses braces.",
        })


def test_public_projection_drops_evidence_sources_and_provider_fields():
    internal = {"flashcards": [{
        **grounded_card(),
        "source_metadata": {"private": "source"},
        "provider": "secret-provider",
        "prompt": "secret-prompt",
    }]}

    public = FlashcardService.to_public_result(internal)

    assert public == {"flashcards": [{
        "front_text": grounded_card()["front_text"],
        "back_text": ANSWER,
        "topic": "Python",
        "difficulty": "easy",
    }]}


@pytest.mark.asyncio
async def test_legacy_non_grounded_generation_remains_compatible():
    legacy = {
        "front_text": "Python là gì?",
        "back_text": "Ngôn ngữ lập trình",
        "topic": "Python",
        "difficulty": "easy",
    }
    service, _ = service_for(legacy)

    result = await service.generate_flashcards(
        "Tạo flashcard", topic="Python", count=1, difficulty="easy"
    )

    assert result == {"flashcards": [legacy]}
