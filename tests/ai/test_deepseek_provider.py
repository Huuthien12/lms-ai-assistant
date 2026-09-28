import pytest
import httpx
from unittest.mock import AsyncMock, patch
from backend.services.ai.deepseek_provider import DeepSeekProvider

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