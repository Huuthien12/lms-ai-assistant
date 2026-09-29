import pytest
import json
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
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng")
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
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng", source_metadata=meta)
    assert res["sources"] == [meta]

@pytest.mark.asyncio
async def test_no_source_input_no_fabrication(mock_orchestrator):
    service = ExplanationService(mock_orchestrator)
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng", source_metadata=None)
    assert res["sources"] == []

@pytest.mark.asyncio
async def test_provider_error_propagates_failure(mock_orchestrator):
    mock_orchestrator.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="mock", model="mock", content="Service unavailable", error_code="HTTP_503", latency_ms=5.0
    ))
    service = ExplanationService(mock_orchestrator)
    res = await service.generate_explanation("Hỏi?", "Sai", "Đúng")
    assert res["status"] == "error"
    assert res["error_code"] == "HTTP_503"
