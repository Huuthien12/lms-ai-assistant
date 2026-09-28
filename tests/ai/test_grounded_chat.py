import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.grounded_chat import GroundedChatService

@pytest.mark.asyncio
async def test_grounded_chat_success():
    mock_orchestrator = AsyncMock(spec=AIOrchestrator)
    mock_orchestrator.generate.return_value = LLMResult(
        status="success",
        provider="deepseek",
        model="chat",
        content="Đây là câu trả lời dựa trên ngữ cảnh.",
        latency_ms=120
    )

    chat_service = GroundedChatService(orchestrator=mock_orchestrator)
    docs = ["Python là một ngôn ngữ lập trình bậc cao."]
    result = await chat_service.chat(user_query="Python là gì?", context_documents=docs)

    assert result.status == "success"
    assert "câu trả lời" in result.content
    mock_orchestrator.generate.assert_awaited_once()
    
    # Kiểm tra xem system prompt có chứa ngữ cảnh không
    call_kwargs = mock_orchestrator.generate.await_args.kwargs
    assert "Python là một ngôn ngữ lập trình bậc cao." in call_kwargs["system_prompt"]