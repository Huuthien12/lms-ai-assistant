import pytest
import json
import ast
import inspect
from copy import deepcopy
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


def grounded_input(**overrides):
    request = dict(topic="Programming", count=1, difficulty="easy",
                   retrieved_context="Python is a programming language.")
    request.update(overrides)
    return request


@pytest.mark.asyncio
async def test_grounded_generation_prompt_and_exact_count(mock_orchestrator):
    service = FlashcardService(mock_orchestrator)
    result = await service.generate_grounded_flashcards(**grounded_input(), temperature=0)
    assert result == {"flashcards": [{"front_text": "Python là gì?",
        "back_text": "Ngôn ngữ lập trình bậc cao", "topic": "Programming", "difficulty": "easy"}]}
    call = mock_orchestrator.generate.call_args.kwargs
    assert json.loads(call["prompt"]) == {
        "topic": "Programming", "count": 1, "difficulty": "easy",
        "trusted_retrieved_context": grounded_input()["retrieved_context"],
    }
    for instruction in ("exactly 1", "only the supplied trusted", "do not use outside knowledge",
                        "Do not invent citations", "valid JSON only", "front_text", "back_text",
                        "topic", "difficulty", "do not output source_metadata"):
        assert instruction in call["system_prompt"]
    assert call["temperature"] == 0
    mock_orchestrator.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_grounded_generation_uses_trusted_topic_and_difficulty(mock_orchestrator):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["flashcards"][0].update(topic="Model topic", difficulty="hard")
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    result = await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input())
    assert result["flashcards"][0]["topic"] == "Programming"
    assert result["flashcards"][0]["difficulty"] == "easy"


@pytest.mark.asyncio
async def test_count_mismatch_and_upper_bound(mock_orchestrator):
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await service.generate_grounded_flashcards(**grounded_input(count=2))
    card = json.loads(mock_orchestrator.generate.return_value.content)["flashcards"][0]
    mock_orchestrator.generate.return_value.content = json.dumps({"flashcards": [card] * 50})
    assert len((await service.generate_grounded_flashcards(**grounded_input(count=50)))["flashcards"]) == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1, 51, True, False, "1", 1.0, None])
async def test_invalid_count_before_llm(mock_orchestrator, count):
    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_REQUEST"):
        await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input(count=count))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["", " \n\t", None, []])
async def test_empty_context_before_llm(mock_orchestrator, context):
    with pytest.raises(ValueError, match="^INSUFFICIENT_GROUNDED_CONTEXT$"):
        await FlashcardService(mock_orchestrator).generate_grounded_flashcards(
            **grounded_input(retrieved_context=context))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"topic": " "}, {"topic": None}, {"topic": 1},
    {"difficulty": "expert"}, {"difficulty": None}, {"difficulty": []},
    {"source_metadata": "bad"}, {"source_metadata": [None]},
])
async def test_invalid_request_before_llm(mock_orchestrator, overrides):
    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_REQUEST"):
        await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input(**overrides))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"front_text": " "}, {"back_text": " "}, {"front_text": 1}, {"back_text": None},
    {"topic": " "}, {"topic": None}, {"topic": []},
    {"difficulty": "expert"}, {"difficulty": None}, {"difficulty": []},
])
async def test_invalid_generated_fields(mock_orchestrator, mutation):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["flashcards"][0].update(mutation)
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    with pytest.raises(ValueError, match="^INVALID_FLASHCARD_SCHEMA$"):
        await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input())


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "secret raw model text", '{"secret":', "[]", "null", "{}",
    '{"flashcards": []}', '{"flashcards": [null]}', '{"flashcards": {}}',
    '{"flashcards": [{"front_text": "front", "back_text": "back", "difficulty": "easy"}]}',
    '{"flashcards": [{"front_text": "front", "back_text": "back", "topic": "topic"}]}',
])
async def test_invalid_output_safe(mock_orchestrator, content):
    mock_orchestrator.generate.return_value.content = content
    with pytest.raises(ValueError) as raised:
        await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input())
    assert str(raised.value) == "INVALID_FLASHCARD_SCHEMA"
    assert raised.value.__suppress_context__ or raised.value.__context__ is None


@pytest.mark.asyncio
async def test_front_back_aliases(mock_orchestrator):
    mock_orchestrator.generate.return_value.content = json.dumps({"flashcards": [
        {"front": " Front ", "back": " Back ", "topic": " Topic ", "difficulty": "mixed"}]})
    result = await FlashcardService(mock_orchestrator).generate_grounded_flashcards(**grounded_input())
    assert result == {"flashcards": [{"front_text": "Front", "back_text": "Back",
                                      "topic": "Programming", "difficulty": "easy"}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, {}, [], {"source_id": "real", "metadata": {"page": 2}},
    [{"source_id": "real", "metadata": {"page": 2}}]])
async def test_caller_sources_only_and_deep_copy(mock_orchestrator, metadata):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["source_metadata"] = {"url": "fabricated"}
    data["flashcards"][0].update(source_metadata={"url": "fabricated"}, sources=[{"url": "fabricated"}])
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    expected = deepcopy(metadata)
    result = await FlashcardService(mock_orchestrator).generate_grounded_flashcards(
        **grounded_input(), source_metadata=metadata)
    card = result["flashcards"][0]
    assert "sources" not in card
    assert "source_metadata" not in result
    if metadata is None:
        assert "source_metadata" not in card
    else:
        assert card["source_metadata"] == expected
        if metadata:
            source = metadata if isinstance(metadata, dict) else metadata[0]
            source["metadata"]["page"] = 99
            assert card["source_metadata"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("raises", [False, True])
async def test_safe_provider_failures(mock_orchestrator, legacy, raises):
    if raises:
        mock_orchestrator.generate.side_effect = RuntimeError("secret exception details")
    else:
        mock_orchestrator.generate.return_value = LLMResult(
            status="error", provider="private", model="private", latency_ms=0,
            content="secret provider content", error_code="secret error")
    service = FlashcardService(mock_orchestrator)
    with pytest.raises(ValueError) as raised:
        if legacy:
            await service.generate_flashcards("Tạo flashcard")
        else:
            await service.generate_grounded_flashcards(**grounded_input())
    assert str(raised.value) == "FLASHCARD_GENERATION_FAILED"
    assert raised.value.__suppress_context__ or raised.value.__context__ is None


@pytest.mark.asyncio
async def test_legacy_prompt_does_not_masquerade_as_retrieval(mock_orchestrator):
    service = FlashcardService(mock_orchestrator)
    service.generate_grounded_flashcards = AsyncMock(side_effect=AssertionError("must not delegate"))
    await service.generate_flashcards("Tạo flashcard")
    service.generate_grounded_flashcards.assert_not_called()
    call = mock_orchestrator.generate.call_args.kwargs
    payload = json.loads(call["prompt"])
    assert payload["legacy_prompt"] == "Tạo flashcard"
    assert "trusted_retrieved_context" not in payload
    assert "retrieved_context" not in payload
    assert "non-grounded" in call["system_prompt"]


def test_service_generation_only_through_orchestrator():
    import backend.services.ai.flashcard_service as module

    tree = ast.parse(inspect.getsource(module))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert [name for name in imports if name.startswith("backend.")] == ["backend.services.ai.orchestrator"]
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute) and node.func.attr == "generate"]
    assert len(calls) == 1
    assert ast.unparse(calls[0].func) == "self.orchestrator.generate"
