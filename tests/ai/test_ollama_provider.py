import httpx
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.ai.grounded_chat import GroundedChatRequest, GroundedChatService, RetrievedContextItem
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult, safe_result
from types import MappingProxyType


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


@pytest.mark.asyncio
@pytest.mark.parametrize("options", [None, "SECRET_PAYLOAD", 1, True, [], [("SECRET", 1)]])
async def test_invalid_options_returns_safe_result_without_http(options, caplog):
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        result = await OllamaProvider().generate("Hi", options=options)
    assert isinstance(result, LLMResult)
    assert result.status == "error" and result.error_code == "INVALID_REQUEST"
    assert result.provider == "ollama" and result.model == "qwen2.5:3b"
    assert result.content == "" and result.fallback_used is False
    assert safe_result(result).error_code == "INVALID_REQUEST"
    assert "SECRET" not in repr(result) + caplog.text
    post.assert_not_called()


@pytest.mark.asyncio
async def test_custom_mapping_and_sampling_options_preserved():
    original = {"num_ctx": 2048, "temperature": 0.9}
    options = MappingProxyType(original)
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=httpx.Response(
        200, json={"message": {"content": "OK"}},
    )) as post:
        result = await OllamaProvider().generate(
            "Hi", options=options, temperature=0, top_p=0.8, seed=42, max_tokens=20)
    assert result.status == "success"
    assert post.call_args.kwargs["json"]["options"] == {
        "num_ctx": 2048, "temperature": 0, "top_p": 0.8, "seed": 42, "num_predict": 20,
    }
    assert original == {"num_ctx": 2048, "temperature": 0.9}
