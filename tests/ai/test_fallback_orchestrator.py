import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.provider_base import LLMResult

@pytest.fixture
def mock_primary():
    return MagicMock()

@pytest.fixture
def mock_fallback():
    return MagicMock()

@pytest.mark.asyncio
async def test_primary_success(mock_primary, mock_fallback):
    mock_primary.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="primary", model="m1", content="Primary OK", latency_ms=10.0
    ))
    provider = FallbackAIProvider(mock_primary, mock_fallback)
    res = await provider.generate("test prompt")

    assert res.status == "success"
    assert res.content == "Primary OK"
    mock_fallback.generate.assert_not_called()

@pytest.mark.asyncio
@pytest.mark.parametrize("err_code", ["HTTP_429", "HTTP_500", "HTTP_503", "TIMEOUT_OR_NETWORK_ERROR"])
async def test_retryable_errors_trigger_fallback(mock_primary, mock_fallback, err_code):
    mock_primary.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="primary", model="m1", content="Error", error_code=err_code, latency_ms=10.0
    ))
    mock_fallback.generate = AsyncMock(return_value=LLMResult(
        status="success", provider="fallback", model="m2", content="Fallback OK", latency_ms=15.0
    ))

    provider = FallbackAIProvider(mock_primary, mock_fallback)
    res = await provider.generate("test prompt")

    assert res.status == "success"
    assert res.content == "Fallback OK"
    assert res.fallback_used is True
    mock_fallback.generate.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize("err_code", ["HTTP_400", "HTTP_401", "UNKNOWN_ERROR", None])
async def test_non_retryable_errors_do_not_trigger_fallback(mock_primary, mock_fallback, err_code):
    mock_primary.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="primary", model="m1", content="Client/Unknown Error", error_code=err_code, latency_ms=10.0
    ))

    provider = FallbackAIProvider(mock_primary, mock_fallback)
    res = await provider.generate("test prompt")

    assert res.status == "error"
    assert res.error_code == (err_code or "UNKNOWN_ERROR")
    mock_fallback.generate.assert_not_called()

@pytest.mark.asyncio
async def test_retryable_primary_plus_fallback_failure(mock_primary, mock_fallback):
    mock_primary.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="primary", model="m1", content="Primary Error", error_code="HTTP_503", latency_ms=10.0
    ))
    mock_fallback.generate = AsyncMock(return_value=LLMResult(
        status="error", provider="fallback", model="m2", content="Fallback Error", error_code="HTTP_500", latency_ms=12.0
    ))

    provider = FallbackAIProvider(mock_primary, mock_fallback)
    res = await provider.generate("test prompt")

    assert res.status == "error"
    assert res.content == ""
    assert res.fallback_used is True
    assert res.provider == "fallback"
    assert res.model == "m2"
    mock_fallback.generate.assert_called_once()
