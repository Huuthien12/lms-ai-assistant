import pytest
import json
from copy import deepcopy
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


def grounded_input(**overrides):
    request = dict(topic="Python", question_count=1, difficulty="medium",
                   question_types=["mcq"], retrieved_context="Python is a programming language.")
    request.update(overrides)
    return request


@pytest.mark.asyncio
async def test_grounded_internal_and_public_defaults(mock_orchestrator):
    service = QuizService(mock_orchestrator)
    internal = await service.generate_grounded_quiz(**grounded_input(), client_facing=False)
    assert internal["questions"][0]["correct_option_id"] == "A"
    assert internal["questions"][0]["explanation"]
    public = await service.generate_grounded_quiz(**grounded_input())
    assert set(public["questions"][0]) == {"question", "type", "options"}
    assert all(set(option) == {"id", "text"} for option in public["questions"][0]["options"])


@pytest.mark.asyncio
async def test_legacy_prompt_is_non_grounded_and_public_safe(mock_orchestrator):
    service = QuizService(mock_orchestrator)
    service.generate_grounded_quiz = AsyncMock(side_effect=AssertionError("must not delegate"))
    result = await service.generate_quiz("Tạo quiz Python")
    service.generate_grounded_quiz.assert_not_called()
    call = mock_orchestrator.generate.call_args.kwargs
    payload = json.loads(call["prompt"])
    assert payload["legacy_prompt"] == "Tạo quiz Python"
    assert "retrieved_context" not in payload
    assert "non-grounded" in call["system_prompt"]
    assert set(result["questions"][0]) == {"question", "type", "options"}


@pytest.mark.asyncio
async def test_legacy_count_and_caller_sources(mock_orchestrator):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["questions"][0]["source_metadata"] = {"source_id": "invented"}
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    service = QuizService(mock_orchestrator)
    result = await service.generate_quiz("Tạo quiz Python", client_facing=False)
    assert "source_metadata" not in result["questions"][0]
    sources = [{"source_id": "caller"}]
    result = await service.generate_quiz(
        "Tạo quiz Python", client_facing=False, source_metadata=sources)
    assert result["questions"][0]["source_metadata"] == sources
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_quiz("Tạo quiz Python", question_count=2)


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_legacy_provider_failure_is_safe(mock_orchestrator, raises):
    if raises:
        mock_orchestrator.generate.side_effect = RuntimeError("secret provider details")
    else:
        mock_orchestrator.generate.return_value = LLMResult(
            status="error", provider="private", model="private", latency_ms=0,
            content="secret provider details", error_code="private error")
    with pytest.raises(ValueError, match="^QUIZ_GENERATION_FAILED$"):
        await QuizService(mock_orchestrator).generate_quiz("Tạo quiz Python")


@pytest.mark.asyncio
@pytest.mark.parametrize("context", ["", "   \n\t", None, []])
async def test_empty_context_rejected_before_llm(mock_orchestrator, context):
    with pytest.raises(ValueError, match="^INSUFFICIENT_GROUNDED_CONTEXT$"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(
            **grounded_input(retrieved_context=context))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [0, -1, 21, True, 1.5, "1", None])
async def test_invalid_count_rejected_before_llm(mock_orchestrator, count):
    with pytest.raises(ValueError, match="INVALID_QUIZ_REQUEST"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(
            **grounded_input(question_count=count))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("types", [[], ["tf"], ["mcq", "tf"], "mcq", None])
async def test_unsupported_question_types(mock_orchestrator, types):
    with pytest.raises(ValueError, match="INVALID_QUIZ_REQUEST"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(
            **grounded_input(question_types=types))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
async def test_exact_count_and_prompt_contract(mock_orchestrator):
    service = QuizService(mock_orchestrator)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await service.generate_grounded_quiz(**grounded_input(question_count=2))
    call = mock_orchestrator.generate.call_args.kwargs
    assert json.loads(call["prompt"])["retrieved_context"] == grounded_input()["retrieved_context"]
    for instruction in ("exactly 2", "outside knowledge", "valid JSON only", "MCQ only",
                        "correct_option_id", "explanation", "Do not invent citations"):
        assert instruction in call["system_prompt"]
    question = json.loads(mock_orchestrator.generate.return_value.content)["questions"][0]
    mock_orchestrator.generate.return_value.content = json.dumps({"questions": [
        {**question, "question": f"Distinct question {index}"} for index in range(20)]})
    result = await service.generate_grounded_quiz(**grounded_input(question_count=20))
    assert len(result["questions"]) == 20


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", [
    {"options": [{"id": "A", "text": "Only option"}]},
    {"options": [{"id": "A", "text": "First"}, {"id": " A ", "text": "Second"}]},
    {"options": [{"id": "A", "text": "   "}, {"id": "B", "text": "Second"}]},
    {"correct_option_id": "C"}, {"correct_option_id": []},
    {"question": "   "}, {"type": "tf"}, {"explanation": ""},
])
async def test_grounded_business_validation(mock_orchestrator, mutation):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["questions"][0].update(mutation)
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input())


@pytest.mark.asyncio
async def test_model_sources_removed_caller_sources_preserved(mock_orchestrator):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["source_metadata"] = {"url": "invented"}
    data["questions"][0]["source_metadata"] = {"url": "invented"}
    data["questions"][0]["options"][0]["is_correct"] = True
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    service = QuizService(mock_orchestrator)
    without_sources = await service.generate_grounded_quiz(**grounded_input(), client_facing=False)
    assert "source_metadata" not in without_sources["questions"][0]
    sources = [{"source_id": "real", "title": "Lecture", "metadata": {"page": 2}}]
    expected = deepcopy(sources)
    internal = await service.generate_grounded_quiz(
        **grounded_input(), source_metadata=sources, client_facing=False)
    assert internal["questions"][0]["source_metadata"] == expected
    sources[0]["metadata"]["page"] = 99
    assert internal["questions"][0]["source_metadata"] == expected
    public = service.to_public_result(internal)
    assert set(public["questions"][0]) == {"question", "type", "options"}
    assert "is_correct" not in public["questions"][0]["options"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["secret raw model text", "{\"secret\":", "[]", '{"questions": []}'])
async def test_invalid_output_errors_do_not_expose_raw(mock_orchestrator, raw):
    mock_orchestrator.generate.return_value.content = raw
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as raised:
        await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input())
    assert raw not in str(raised.value)
    assert raised.value.__suppress_context__ or raised.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_provider_failure_is_safe(mock_orchestrator, raises):
    if raises:
        mock_orchestrator.generate.side_effect = RuntimeError("secret provider details")
    else:
        mock_orchestrator.generate.return_value = LLMResult(
            status="error", provider="private", model="private", latency_ms=0,
            content="secret provider details", error_code="private error")
    with pytest.raises(ValueError, match="^QUIZ_GENERATION_FAILED$"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input())


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["What is Python?", "  what   IS\npython? "])
async def test_duplicate_questions_rejected(mock_orchestrator, variant):
    question = json.loads(mock_orchestrator.generate.return_value.content)["questions"][0]
    question["question"] = "What is Python?"
    mock_orchestrator.generate.return_value.content = json.dumps({"questions": [question, {**question, "question": variant}]})
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA") as error:
        await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input(question_count=2))
    assert variant not in str(error.value)
    mock_orchestrator.generate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", ["First option", "  FIRST\t option "])
async def test_duplicate_option_text_rejected(mock_orchestrator, variant):
    data = json.loads(mock_orchestrator.generate.return_value.content)
    data["questions"][0]["options"] = [{"id": "A", "text": "First option"}, {"id": "B", "text": variant}]
    mock_orchestrator.generate.return_value.content = json.dumps(data)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input())


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("bad", [None, {"content": "SECRET"}, object()])
async def test_malformed_result_is_generation_failure(mock_orchestrator, legacy, bad):
    mock_orchestrator.generate.return_value = bad
    with pytest.raises(ValueError) as error:
        if legacy:
            await QuizService(mock_orchestrator).generate_quiz("Quiz")
        else:
            await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input())
    assert str(error.value) == "QUIZ_GENERATION_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("metadata", ["SECRET", 1, [None], ["SECRET"]])
async def test_invalid_sources_rejected_before_provider(mock_orchestrator, legacy, metadata):
    with pytest.raises(ValueError, match="^INVALID_QUIZ_REQUEST") as error:
        if legacy:
            await QuizService(mock_orchestrator).generate_quiz("Quiz", source_metadata=metadata)
        else:
            await QuizService(mock_orchestrator).generate_grounded_quiz(**grounded_input(), source_metadata=metadata)
    assert "SECRET" not in str(error.value)
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [{"source_id": "trusted", "nested": {"page": 1}},
                                      [{"source_id": "trusted", "nested": {"page": 1}}]])
async def test_sources_snapshot_before_provider_and_public_safe(mock_orchestrator, metadata):
    original = deepcopy(metadata)
    content = mock_orchestrator.generate.return_value
    async def generate(**kwargs):
        source = metadata if isinstance(metadata, dict) else metadata[0]
        source["nested"]["page"] = 99
        return content
    mock_orchestrator.generate.side_effect = generate
    service = QuizService(mock_orchestrator)
    result = await service.generate_grounded_quiz(**grounded_input(), source_metadata=metadata, client_facing=False)
    assert result["questions"][0]["source_metadata"] == original
    assert "source_metadata" not in service.to_public_result(result)["questions"][0]
