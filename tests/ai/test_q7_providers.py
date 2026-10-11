import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services.ai.deepseek_provider import DeepSeekProvider
from backend.services.ai.fallback_provider import FallbackAIProvider
from backend.services.ai.ollama_provider import OllamaProvider
from backend.services.ai.orchestrator import AIOrchestrator, build_default_orchestrator
from backend.services.ai.provider_base import LLMResult


@pytest.fixture(autouse=True)
def mocked_http():
    # Every network entry point is mocked, including tests not expecting HTTP.
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post, \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        post.side_effect = AssertionError("Unexpected HTTP POST")
        get.side_effect = AssertionError("Unexpected HTTP GET")
        yield post, get


def test_ollama_defaults():
    provider = OllamaProvider()
    assert provider.base_url == "http://localhost:11434"
    assert provider.model == "qwen2.5:3b"
    assert provider.timeout_seconds == 30


@pytest.mark.asyncio
async def test_ollama_success_and_payload(mocked_http):
    post, _ = mocked_http
    post.side_effect = None
    post.return_value = httpx.Response(200, json={
        "done": True, "message": {"content": "Hello"},
        "prompt_eval_count": 10, "eval_count": 5,
    })
    result = await OllamaProvider().generate("Hi", "System", temperature=0, max_tokens=20, stream=True)
    assert result.status == "success"
    assert result.provider == "ollama" and result.model == "qwen2.5:3b"
    assert result.content == "Hello" and result.fallback_used is False
    assert result.latency_ms >= 0
    assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    post.assert_awaited_once_with("http://localhost:11434/api/chat", json={
        "model": "qwen2.5:3b", "stream": False,
        "messages": [{"role": "system", "content": "System"}, {"role": "user", "content": "Hi"}],
        "options": {"temperature": 0, "num_predict": 20},
    })


@pytest.mark.asyncio
@pytest.mark.parametrize("exception,code", [
    (httpx.ReadTimeout("SECRET"), "TIMEOUT_OR_NETWORK_ERROR"),
    (httpx.ConnectError("SECRET"), "TIMEOUT_OR_NETWORK_ERROR"),
    (RuntimeError("SECRET"), "UNKNOWN_ERROR"),
])
async def test_ollama_safe_exception(mocked_http, exception, code, caplog):
    post, _ = mocked_http
    post.side_effect = exception
    result = await OllamaProvider().generate("Hi")
    assert result.status == "error" and result.error_code == code
    assert result.content == "" and not result.fallback_used
    assert "SECRET" not in str(result) + caplog.text
    assert post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
async def test_ollama_http_error(mocked_http, status):
    post, _ = mocked_http
    post.side_effect = None
    post.return_value = httpx.Response(status, text="SECRET_BODY")
    result = await OllamaProvider().generate("Hi")
    assert result.error_code == f"HTTP_{status}"
    assert result.content == "" and "SECRET" not in str(result)
    assert post.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [
    None, [], {}, {"done": True}, {"done": False, "message": {"content": "SECRET"}},
    {"done": True, "message": {"content": None}},
    {"done": True, "message": {"content": "  "}},
])
async def test_ollama_malformed_response(mocked_http, data):
    post, _ = mocked_http
    post.side_effect = None
    post.return_value = httpx.Response(200, content=json.dumps(data))
    result = await OllamaProvider().generate("Hi")
    assert result.error_code == "INVALID_RESPONSE"
    assert result.content == "" and "SECRET" not in str(result)


@pytest.mark.asyncio
async def test_ollama_invalid_json(mocked_http):
    post, _ = mocked_http
    post.side_effect = None
    post.return_value = httpx.Response(200, text="SECRET_INVALID_JSON")
    result = await OllamaProvider().generate("Hi")
    assert result.error_code == "INVALID_RESPONSE"
    assert "SECRET" not in str(result)


@pytest.mark.parametrize("key", [None, "", "  ", "\t\n"])
def test_no_key_uses_ollama(monkeypatch, key):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    if key is not None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", key)
    assert isinstance(build_default_orchestrator().default_provider, OllamaProvider)


def test_configured_factory_and_overrides(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", " SECRET_KEY ")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:12345/")
    monkeypatch.setenv("OLLAMA_MODEL", "custom:3b")
    provider = build_default_orchestrator().default_provider
    assert isinstance(provider, FallbackAIProvider)
    assert isinstance(provider.primary_provider, DeepSeekProvider)
    assert isinstance(provider.fallback_provider, OllamaProvider)
    assert provider.fallback_provider.base_url == "http://localhost:12345"
    assert provider.fallback_provider.model == "custom:3b"
    assert "SECRET_KEY" not in repr(provider.primary_provider)
    assert isinstance(build_default_orchestrator({}).default_provider, OllamaProvider)


@pytest.mark.parametrize("key", [None, "", "  ", "\t\n"])
def test_deepseek_unconfigured_key(key):
    with pytest.raises(ValueError) as error:
        DeepSeekProvider(key)
    assert str(key) not in str(error.value) if key else True


@pytest.mark.asyncio
async def test_deepseek_secret_safe_health_and_failure(mocked_http, caplog):
    provider = DeepSeekProvider("SECRET_KEY")
    health = await provider.health_check()
    assert health == {"provider": "deepseek", "model": "deepseek-chat", "status": "available"}
    post, _ = mocked_http
    post.side_effect = RuntimeError("SECRET_KEY")
    result = await provider.generate("Hi")
    assert result.error_code == "UNKNOWN_ERROR" and result.content == ""
    assert "SECRET_KEY" not in str(health) + repr(provider) + str(result) + caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("models,status", [
    ([{"name": "qwen2.5:3b"}], "available"),
    ([{"name": "other"}], "unavailable"), ([], "unavailable"),
    (None, "unavailable"),
])
async def test_ollama_health(mocked_http, models, status):
    _, get = mocked_http
    get.side_effect = None
    get.return_value = httpx.Response(200, json={"models": models, "secret": "SECRET"})
    health = await OllamaProvider().health_check()
    assert health == {"provider": "ollama", "model": "qwen2.5:3b", "status": status}
    get.assert_awaited_once_with("http://localhost:11434/api/tags")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "exception", "malformed"])
async def test_ollama_health_safe_failure(mocked_http, failure):
    _, get = mocked_http
    get.side_effect = None
    get.return_value = httpx.Response(500, text="SECRET")
    if failure == "exception":
        get.side_effect = RuntimeError("SECRET")
    elif failure == "malformed":
        get.return_value = httpx.Response(200, text="SECRET")
    health = await OllamaProvider().health_check()
    assert health["status"] == "unavailable"
    assert "SECRET" not in str(health)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [
    "HTTP_429", "HTTP_500", "HTTP_502", "HTTP_503", "HTTP_504",
    "TIMEOUT_OR_NETWORK_ERROR", "RATE_LIMIT", "SERVICE_UNAVAILABLE",
])
@pytest.mark.parametrize("fallback_status", ["success", "error", "exception"])
async def test_real_provider_chain_mocked(code, fallback_status):
    primary, local = DeepSeekProvider("SECRET_KEY"), OllamaProvider()
    primary.generate = AsyncMock(return_value=LLMResult(
        "error", "deepseek", primary.model, "SECRET_PRIMARY", 1, error_code=code))
    if fallback_status == "exception":
        local.generate = AsyncMock(side_effect=RuntimeError("SECRET_EXCEPTION"))
    else:
        local.generate = AsyncMock(return_value=LLMResult(
            fallback_status, "ollama", local.model,
            "Local answer" if fallback_status == "success" else "SECRET_FALLBACK", 2,
            error_code=None if fallback_status == "success" else "HTTP_500"))
    original = local.generate.return_value if fallback_status != "exception" else None
    result = await AIOrchestrator(FallbackAIProvider(primary, local)).generate("Hi", "System")
    assert result.fallback_used is True
    assert result.provider == "ollama" and result.model == local.model
    assert result.status == ("success" if fallback_status == "success" else "error")
    assert "SECRET" not in str(result)
    local.generate.assert_awaited_once_with(prompt="Hi", system_prompt="System")
    if original:
        assert original.fallback_used is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [
    ("success", None), ("error", "HTTP_400"), ("error", "HTTP_401"),
    ("error", "UNKNOWN_ERROR"), ("error", None), ("error", "SECRET_CODE"),
])
async def test_no_fallback_for_success_or_nonretryable(status, code):
    primary, local = DeepSeekProvider("key"), OllamaProvider()
    primary.generate = AsyncMock(return_value=LLMResult(
        status, "deepseek", primary.model, "OK" if status == "success" else "SECRET", 1,
        error_code=code))
    local.generate = AsyncMock()
    result = await FallbackAIProvider(primary, local).generate("Hi")
    assert result.provider == "deepseek" and not result.fallback_used
    assert "SECRET" not in str(result)
    local.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("primary_status,local_status,overall", [
    ("unavailable", "unavailable", "unavailable"),
    ("unconfigured", "unconfigured", "unconfigured"),
    ("unavailable", "available", "available"),
    ("available", "unavailable", "available"),
])
async def test_composed_health_safe_status(primary_status, local_status, overall):
    primary, local = DeepSeekProvider("SECRET_KEY"), OllamaProvider()
    primary.health_check = AsyncMock(return_value={"status": primary_status, "api_key": "SECRET_KEY"})
    local.health_check = AsyncMock(return_value={"status": local_status, "headers": "SECRET"})
    health = await AIOrchestrator(FallbackAIProvider(primary, local)).health_check()
    assert health["status"] == overall
    assert health["primary"] == {"provider": "deepseek", "model": primary.model, "status": primary_status}
    assert health["fallback"] == {"provider": "ollama", "model": local.model, "status": local_status}
    assert "SECRET" not in str(health)
    primary.health_check.assert_awaited_once()
    local.health_check.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_and_primary_exception_safety(caplog):
    primary, local = DeepSeekProvider("key"), OllamaProvider()
    primary.generate = AsyncMock(side_effect=RuntimeError("SECRET"))
    primary.health_check = AsyncMock(side_effect=RuntimeError("SECRET"))
    local.generate = AsyncMock()
    for provider in (primary, FallbackAIProvider(primary, local)):
        result = await AIOrchestrator(provider).generate("Hi")
        assert result.error_code == "UNKNOWN_ERROR"
        assert result.provider == "deepseek" and not result.fallback_used
        assert "SECRET" not in str(result) + caplog.text
    health = await AIOrchestrator(primary).health_check()
    assert health["status"] == "unavailable"
    assert "SECRET" not in str(health) + caplog.text
    local.generate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["deepseek-response", "ollama-options"])
async def test_invalid_response_and_request_do_not_trigger_fallback(mocked_http, kind):
    local = OllamaProvider()
    if kind == "deepseek-response":
        primary = DeepSeekProvider("SECRET_KEY")
        post, _ = mocked_http
        post.side_effect = None
        post.return_value = httpx.Response(200, text="SECRET_INVALID_JSON")
        kwargs, code = {}, "INVALID_RESPONSE"
    else:
        primary = OllamaProvider()
        kwargs, code = {"options": "SECRET_PAYLOAD"}, "INVALID_REQUEST"
    local.generate = AsyncMock()
    result = await AIOrchestrator(FallbackAIProvider(primary, local)).generate("Hi", **kwargs)
    assert result.status == "error" and result.error_code == code
    assert result.provider == primary.provider and result.model == primary.model
    assert result.content == "" and result.fallback_used is False
    assert "SECRET" not in repr(result)
    local.generate.assert_not_called()
