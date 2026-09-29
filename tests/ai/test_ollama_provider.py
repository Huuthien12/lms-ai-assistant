import httpx
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.ai.grounded_chat import GroundedChatRequest, GroundedChatService, RetrievedContextItem
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator


@pytest.mark.asyncio
async def test_ollama_grounded_chat_preserves_context_and_reports_local_metadata():
    provider = OllamaProvider()
    response = httpx.Response(200, json={"message": {"content": "Grounded local answer."}, "eval_count": 4})
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=response) as post:
        result = await GroundedChatService(AIOrchestrator(provider)).chat(GroundedChatRequest(
            query="Question", contexts=[RetrievedContextItem(text="Retrieved excerpt")],
            course_id="INT1339", kb_name="int1339-python",
        ))

    assert result.answer == "Grounded local answer."
    assert result.ai == {"provider": "ollama", "model": "qwen2.5:3b", "fallback_used": False}
    assert "Retrieved excerpt" in post.await_args.kwargs["json"]["messages"][-1]["content"]


@pytest.mark.asyncio
async def test_ollama_provider_returns_existing_error_contract_on_failure():
    provider = OllamaProvider()
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.NetworkError("offline")):
        result = await provider.generate("Question")

    assert result.status == "error"
    assert result.provider == "ollama"
    assert result.model == "qwen2.5:3b"
    assert result.error_code == "TIMEOUT_OR_NETWORK_ERROR"
