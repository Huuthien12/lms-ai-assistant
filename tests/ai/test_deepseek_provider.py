import pytest
import httpx
from unittest.mock import AsyncMock, patch
from backend.services.ai.deepseek_provider import DeepSeekProvider
from backend.services.ai.provider_base import LLMResult
import json

def test_deepseek_provider_init_missing_key():
    with pytest.raises(ValueError):
        DeepSeekProvider(api_key="")

def test_deepseek_provider_init_success():
    provider = DeepSeekProvider(api_key="test-key", model="deepseek-chat")
    assert provider.model == "deepseek-chat"
    assert provider.api_key == "test-key"

@pytest.mark.asyncio
async def test_deepseek_provider_generate_success():
    provider = DeepSeekProvider(api_key="test-key")
    
    mock_response = httpx.Response(
        status_code=200,
        json={
            "choices": [{"message": {"content": "Hello from DeepSeek"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
        }
    )
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await provider.generate(prompt="Hi")
        
        assert result.status == "success"
        assert result.content == "Hello from DeepSeek"
        assert result.provider == "deepseek"
        assert result.fallback_used is False
        assert result.usage["total_tokens"] == 15

@pytest.mark.asyncio
async def test_deepseek_provider_generate_rate_limit():
    provider = DeepSeekProvider(api_key="test-key")
    
    mock_response = httpx.Response(status_code=429)
    
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response
        result = await provider.generate(prompt="Hi")
        
        assert result.status == "error"
        assert result.error_code == "HTTP_429"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    "SECRET_INVALID_JSON", "null", "[]", "42", "{}",
    '{"choices": []}', '{"choices": null}', '{"choices": "SECRET"}',
    '{"choices": [null]}', '{"choices": [{}]}',
    '{"choices": [{"message": null}]}', '{"choices": [{"message": []}]}',
    '{"choices": [{"message": {}}]}',
    *[json.dumps({"choices": [{"message": {"content": value}}]})
      for value in (None, "", "  \n", 1, True, [], {"SECRET": "payload"})],
])
async def test_malformed_success_is_safe_nonretryable_error(body, caplog):
    provider = DeepSeekProvider("SECRET_KEY", model="configured-model")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock,
               return_value=httpx.Response(200, text=body)) as post:
        result = await provider.generate("Hi")
    assert isinstance(result, LLMResult)
    assert result.status == "error" and result.error_code == "INVALID_RESPONSE"
    assert result.provider == "deepseek" and result.model == "configured-model"
    assert result.content == "" and result.fallback_used is False
    assert "SECRET" not in repr(result) + repr(provider) + caplog.text
    post.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("exception", [httpx.ReadTimeout("SECRET_KEY"), httpx.ConnectError("SECRET_KEY")])
async def test_timeout_network_preserves_retry_and_safe_schema(exception, caplog):
    provider = DeepSeekProvider("SECRET_KEY")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=exception) as post:
        result = await provider.generate("Hi")
    assert isinstance(result, LLMResult)
    assert result.status == "error" and result.error_code == "TIMEOUT_OR_NETWORK_ERROR"
    assert result.provider == "deepseek" and result.model == "deepseek-chat"
    assert result.content == "" and result.fallback_used is False
    assert post.await_count == 2
    assert "SECRET_KEY" not in repr(result) + caplog.text
