import pytest
from unittest.mock import AsyncMock
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.fallback_provider import FallbackLLMProvider
from backend.services.ai.orchestrator import AIOrchestrator

@pytest.mark.asyncio
async def test_fallback_success_on_primary():
    primary = AsyncMock()
    primary.generate.return_value = LLMResult(
        status="success", provider="deepseek", model="chat", content="Primary response", latency_ms=100
    )
    fallback = AsyncMock()
    
    fp = FallbackLLMProvider(primary_provider=primary, fallback_provider=fallback)
    result = await fp.generate("Hello")
    
    assert result.status == "success"
    assert result.content == "Primary response"
    assert result.fallback_used is False
    fallback.generate.assert_not_called()

@pytest.mark.asyncio
async def test_fallback_triggers_on_primary_error():
    primary = AsyncMock()
    primary.generate.return_value = LLMResult(
        status="error", provider="deepseek", model="chat", content="", latency_ms=100, error_code="HTTP_500"
    )
    
    fallback = AsyncMock()
    fallback.generate.return_value = LLMResult(
        status="success", provider="openai", model="gpt-4", content="Fallback response", latency_ms=200
    )
    
    fp = FallbackLLMProvider(primary_provider=primary, fallback_provider=fallback)
    result = await fp.generate("Hello")
    
    assert result.status == "success"
    assert result.content == "Fallback response"
    assert result.fallback_used is True
    fallback.generate.assert_awaited_once()

@pytest.mark.asyncio
async def test_orchestrator_execution():
    provider = AsyncMock()
    provider.generate.return_value = LLMResult(
        status="success", provider="deepseek", model="chat", content="Orchestrated", latency_ms=50
    )
    
    orchestrator = AIOrchestrator(default_provider=provider)
    result = await orchestrator.generate("Test prompt")
    
    assert result.status == "success"
    assert result.content == "Orchestrated"