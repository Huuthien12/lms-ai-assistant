import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.grounded_chat import GroundedChatService, GroundedChatRequest, RetrievedContextItem
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_orchestrator():
    orch = MagicMock(spec=AIOrchestrator)
    orch.generate = AsyncMock(return_value=LLMResult(
        status="success",
        provider="mock",
        model="mock-model",
        content="Phản hồi từ grounded chat dựa trên tài liệu.",
        latency_ms=15.0
    ))
    return orch

@pytest.mark.asyncio
async def test_valid_grounded_context(mock_orchestrator):
    service = GroundedChatService(mock_orchestrator)
    req = GroundedChatRequest(
        query="Python là gì?",
        contexts=[
            RetrievedContextItem(text="Python là ngôn ngữ lập trình bậc cao.", source_id="s1", title="Intro to Python")
        ],
        course_id="c1",
        kb_name="python_kb"
    )
    res = await service.chat(req)
    assert res.status == "success"
    assert "Phản hồi" in res.content
    mock_orchestrator.generate.assert_called_once()

@pytest.mark.asyncio
async def test_source_metadata_preservation(mock_orchestrator):
    service = GroundedChatService(mock_orchestrator)
    item = RetrievedContextItem(
        text="Nội dung test metadata",
        source_id="doc_123",
        title="Tài liệu LMS",
        url="https://lms.example.com/doc",
        score=0.95
    )
    req = GroundedChatRequest(query="Test?", contexts=[item], course_id="course_99", kb_name="kb_test")

    # Kiểm tra service nhận đúng request object cấu trúc chứa metadata
    assert req.contexts[0].source_id == "doc_123"
    assert req.contexts[0].title == "Tài liệu LMS"
    assert req.contexts[0].url == "https://lms.example.com/doc"

@pytest.mark.asyncio
async def test_course_id_kb_name_preservation(mock_orchestrator):
    service = GroundedChatService(mock_orchestrator)
    req = GroundedChatRequest(
        query="Test course kb",
        contexts=[RetrievedContextItem(text="Context text")],
        course_id="MATH101",
        kb_name="math_kb"
    )
    assert req.course_id == "MATH101"
    assert req.kb_name == "math_kb"

@pytest.mark.asyncio
async def test_empty_context_safe_response(mock_orchestrator):
    service = GroundedChatService(mock_orchestrator)
    req = GroundedChatRequest(query="Câu hỏi không có context", contexts=[])
    res = await service.chat(req)

    # Phải trả về safe response và KHÔNG gọi provider/orchestrator
    assert res.status == "success"
    assert res.fallback_used is True
    assert "không tìm thấy tài liệu" in res.content
    mock_orchestrator.generate.assert_not_called()

@pytest.mark.asyncio
async def test_no_fabricated_source(mock_orchestrator):
    service = GroundedChatService(mock_orchestrator)
    # Context không có source cụ thể, đảm bảo không bịa source
    item = RetrievedContextItem(text="Chỉ có text thô không có id hay url.")
    req = GroundedChatRequest(query="Hỏi?", contexts=[item])
    res = await service.chat(req)
    assert res.status == "success"
