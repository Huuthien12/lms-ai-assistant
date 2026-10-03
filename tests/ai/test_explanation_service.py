import pytest
import json
import ast
import inspect
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.explanation_service import ExplanationService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=AIOrchestrator)
    valid_json = json.dumps({
        "explanation": "Bạn nhầm lẫn giữa hai khái niệm...",
        "key_concept": "Biến toàn cục"
    })
    orch.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="mock", model="mock", content=valid_json, latency_ms=10.0
    ))
    return orch

@pytest.mark.asyncio
async def test_basic_explanation_success(mock_orchestrator):
    service = ExplanationService(mock_orchestrator)
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng", context="Tài liệu XYZ")
    assert res["status"] == "success"
    assert "explanation" in res
    assert "key_concept" in res

@pytest.mark.asyncio
async def test_supplied_context_included_in_prompt(mock_orchestrator):
    service = ExplanationService(mock_orchestrator)
    await service.generate_explanation("Hỏi?", "Sai", "Đúng", context="Tài liệu XYZ")

    # Kiểm tra orchestrator được gọi với prompt chứa context thực tế
    called_args = mock_orchestrator.generate.call_args
    prompt_sent = called_args.kwargs.get("prompt") or called_args.args[0]
    assert "Tài liệu XYZ" in prompt_sent

@pytest.mark.asyncio
async def test_supplied_source_metadata_preserved(mock_orchestrator):
    service = ExplanationService(mock_orchestrator)
    meta = {"source_id": "src_99", "title": "Lecture 1"}
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng", context="Tài liệu XYZ", source_metadata=meta)
    assert res["sources"] == [meta]

@pytest.mark.asyncio
async def test_no_source_input_no_fabrication(mock_orchestrator):
    service = ExplanationService(mock_orchestrator)
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng", context="Tài liệu XYZ", source_metadata=None)
    assert res["sources"] == []

@pytest.mark.asyncio
async def test_provider_error_propagates_failure(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="mock", model="mock", content="Service unavailable", error_code="HTTP_503", latency_ms=5.0
    ))
    service = ExplanationService(mock_orchestrator)
    with pytest.raises(ValueError, match="^EXPLANATION_GENERATION_FAILED$"):
        await service.generate_explanation("Hỏi?", "Sai", "Đúng", context="Tài liệu XYZ")


def valid_input(**overrides):
    request = dict(question="Question?", student_answer="B", correct_answer="A",
                   context="Trusted retrieved passage")
    request.update(overrides)
    return request


@pytest.mark.asyncio
async def test_prompt_contains_grading_facts_and_grounding_boundary(mock_orchestrator):
    request = valid_input()
    original = deepcopy(request)
    result = await ExplanationService(mock_orchestrator).generate_explanation(**request, temperature=0)
    call = mock_orchestrator.generate.call_args.kwargs
    assert json.loads(call["prompt"]) == {
        "question": request["question"], "student_answer": request["student_answer"],
        "correct_answer": request["correct_answer"], "trusted_retrieved_context": request["context"],
    }
    for instruction in ("only the supplied trusted", "do not use outside knowledge",
                        "invent citations", "only as grading facts", "already authoritative",
                        "do not change or contradict", "do not decide correctness", "valid JSON only"):
        assert instruction in call["system_prompt"]
    assert call["temperature"] == 0
    mock_orchestrator.generate.assert_awaited_once()
    assert request == original
    assert set(result) == {"status", "explanation", "key_concept", "sources"}


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [None, "", " \n\t", [], 123])
async def test_empty_context_rejected_before_llm(mock_orchestrator, context):
    with pytest.raises(ValueError, match="^INSUFFICIENT_GROUNDED_CONTEXT$"):
        await ExplanationService(mock_orchestrator).generate_explanation(**valid_input(context=context))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"question": ""}, {"question": "  "}, {"question": None}, {"question": 12},
    {"correct_answer": ""}, {"correct_answer": "  "}, {"correct_answer": None},
    {"correct_answer": []}, {"student_answer": ""}, {"student_answer": "  "},
    {"student_answer": 12}, {"source_metadata": "untrusted shape"},
    {"source_metadata": [None]},
])
async def test_invalid_input_rejected_before_llm(mock_orchestrator, overrides):
    with pytest.raises(ValueError, match="^INVALID_EXPLANATION_INPUT"):
        await ExplanationService(mock_orchestrator).generate_explanation(**valid_input(**overrides))
    mock_orchestrator.generate.assert_not_called()


@pytest.mark.asyncio
async def test_none_student_answer_is_explicitly_unanswered(mock_orchestrator):
    result = await ExplanationService(mock_orchestrator).generate_explanation(
        **valid_input(student_answer=None))
    call = mock_orchestrator.generate.call_args.kwargs
    assert json.loads(call["prompt"])["student_answer"] is None
    assert "the question was unanswered" in call["system_prompt"]
    assert result["status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [
    "secret raw model text", '{"secret":', "[]", "null",
    '{}', '{"key_concept": "concept"}', '{"explanation": "text"}',
    '{"explanation": " ", "key_concept": "concept"}',
    '{"explanation": "text", "key_concept": " "}',
    '{"explanation": [], "key_concept": "concept"}',
    '{"explanation": "text", "key_concept": 1}',
    '```json\n{"explanation": "text", "key_concept": "concept"}\n```',
])
async def test_invalid_output_is_safe_without_raw_fallback(mock_orchestrator, content):
    mock_orchestrator.generate.return_value.content = content
    with pytest.raises(ValueError) as raised:
        await ExplanationService(mock_orchestrator).generate_explanation(**valid_input())
    assert str(raised.value) == "INVALID_EXPLANATION_SCHEMA"
    assert raised.value.__suppress_context__ or raised.value.__context__ is None


@pytest.mark.asyncio
@pytest.mark.parametrize("metadata", [None, [], {"source_id": "real", "metadata": {"page": 2}},
    [{"source_id": "real", "metadata": {"page": 2}}]])
async def test_only_caller_sources_returned_and_deep_copied(mock_orchestrator, metadata):
    mock_orchestrator.generate.return_value.content = json.dumps({
        "explanation": "Explanation", "key_concept": "Concept",
        "sources": [{"url": "fabricated"}], "source_metadata": {"url": "fabricated"},
        "correct": True, "correct_answer": "model replacement", "score_percent": 100,
    })
    expected = deepcopy([metadata] if isinstance(metadata, dict) else metadata or [])
    result = await ExplanationService(mock_orchestrator).generate_explanation(
        **valid_input(), source_metadata=metadata)
    assert result == dict(status="success", explanation="Explanation", key_concept="Concept", sources=expected)
    if metadata:
        source = metadata if isinstance(metadata, dict) else metadata[0]
        source["metadata"]["page"] = 99
        assert result["sources"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("raises", [False, True])
async def test_provider_details_never_returned(mock_orchestrator, raises):
    if raises:
        mock_orchestrator.generate.side_effect = RuntimeError("secret exception details")
    else:
        mock_orchestrator.generate.return_value = LLMResult(
            status="error", provider="private", model="private", latency_ms=0,
            content="secret provider content", error_code="secret provider error")
    with pytest.raises(ValueError) as raised:
        await ExplanationService(mock_orchestrator).generate_explanation(**valid_input())
    assert str(raised.value) == "EXPLANATION_GENERATION_FAILED"
    assert raised.value.__suppress_context__ or raised.value.__context__ is None


def test_service_has_no_grading_or_provider_dependencies():
    import backend.services.ai.explanation_service as module

    tree = ast.parse(inspect.getsource(module))
    imports = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert [name for name in imports if name.startswith("backend.")] == ["backend.services.ai.orchestrator"]
    generation_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute) and node.func.attr == "generate"]
    assert len(generation_calls) == 1
    assert ast.unparse(generation_calls[0].func) == "self.orchestrator.generate"
