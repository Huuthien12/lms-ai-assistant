import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.model_config import ModelConfig


def config(provider="ollama", **updates):
    values = {"provider":provider, "model":"test-model"}
    if provider != "ollama": values["api_key_env"] = provider.upper()+"_API_KEY"
    values.update(updates)
    return ModelConfig(**values)


@pytest.mark.parametrize("provider", ["ollama", "openai", "gemini", "anthropic", "groq"])
def test_supported_common_model_configuration(provider):
    value=config(provider)
    assert value.provider==provider and value.temperature==0.1
    assert value.max_tokens==1024 and value.timeout_seconds==120


@pytest.mark.parametrize("updates", [
    {"provider":"unknown"}, {"model":" "}, {"temperature":-1},
    {"temperature":2.1}, {"max_tokens":0}, {"timeout_seconds":0},
])
def test_invalid_configuration_rejected(updates):
    values={"provider":"ollama","model":"model",**updates}
    with pytest.raises(ValueError): ModelConfig(**values)


@pytest.mark.asyncio
async def test_local_provider_passes_common_parameters_without_secrets(tmp_path):
    runner=MagicMock(return_value={"status":"success","content":"Answer [Nguồn 1]",
                                   "usage":{"prompt_tokens":10,"completion_tokens":4}})
    provider=DeepTutorProvider(config(),tmp_path,runner)
    result=await provider.generate("fixed prompt","system",temperature=0.2,max_tokens=50)
    assert result.status=="success" and result.content=="Answer [Nguồn 1]"
    request,timeout=runner.call_args.args
    assert request=={"provider":"ollama","model":"test-model","prompt":"fixed prompt",
                     "system_prompt":"system","temperature":0.2,"max_tokens":50,
                     "api_key_env":None,"base_url":None,"timeout_seconds":120}
    assert timeout==120 and result.usage=={"prompt_tokens":10,"completion_tokens":4}


@pytest.mark.asyncio
async def test_cloud_content_is_disabled_by_default(monkeypatch,tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY","SECRET")
    runner=MagicMock()
    result=await DeepTutorProvider(config("openai"),tmp_path,runner).generate("MOODLE CONTENT")
    assert result.error_code=="CLOUD_CONTENT_DISABLED" and result.content==""
    runner.assert_not_called()
    assert "SECRET" not in repr(result)


@pytest.mark.asyncio
async def test_cloud_key_is_read_from_environment_but_never_put_in_request(monkeypatch,tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY","SECRET-GEMINI")
    runner=MagicMock(return_value={"status":"success","content":"Answer"})
    provider=DeepTutorProvider(config("gemini",allow_cloud_document_content=True),tmp_path,runner)
    result=await provider.generate("document")
    assert result.status=="success"
    request=runner.call_args.args[0]
    assert request["api_key_env"]=="GEMINI_API_KEY"
    assert "SECRET-GEMINI" not in repr(request)+repr(result)


@pytest.mark.asyncio
async def test_missing_cloud_key_and_worker_failures_are_safe(monkeypatch,tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY",raising=False)
    runner=MagicMock(side_effect=RuntimeError("SECRET"))
    provider=DeepTutorProvider(config("anthropic",allow_cloud_document_content=True),tmp_path,runner)
    missing=await provider.generate("document")
    assert missing.error_code=="PROVIDER_UNCONFIGURED"
    monkeypatch.setenv("ANTHROPIC_API_KEY","key")
    failed=await provider.generate("document")
    assert failed.error_code=="UNKNOWN_ERROR" and "SECRET" not in repr(failed)


@pytest.mark.asyncio
async def test_timeout_and_provider_error_are_normalized(tmp_path):
    timeout=DeepTutorProvider(config(),tmp_path,MagicMock(side_effect=TimeoutError("SECRET")))
    assert (await timeout.generate("prompt")).error_code=="TIMEOUT_OR_NETWORK_ERROR"
    rejected=DeepTutorProvider(config(),tmp_path,MagicMock(return_value={
        "status":"error","error_code":"PROVIDER_ERROR","private":"SECRET"}))
    result=await rejected.generate("prompt")
    assert result.error_code=="PROVIDER_ERROR" and "SECRET" not in repr(result)


@pytest.mark.asyncio
async def test_empty_response_metadata_survives_worker_bridge(monkeypatch,tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY","key")
    metadata={"content_type":"NoneType","content_length":0,"finish_reason":"length",
              "reasoning_present":True,"reasoning_length":321,"reasoning_tokens":1024,
              "http_status":200,"provider_response_id":"gen-123"}
    runner=MagicMock(return_value={"status":"error","error_code":"EMPTY_RESPONSE",
                                   "metadata":metadata})
    result=await DeepTutorProvider(config(
        "openrouter",allow_cloud_document_content=True),tmp_path,runner).generate("document")
    assert result.error_code=="EMPTY_RESPONSE" and result.metadata==metadata


@pytest.mark.asyncio
async def test_groq_receives_json_mode_and_bounded_timeout_without_key(monkeypatch,tmp_path):
    monkeypatch.setenv("GROQ_API_KEY","SECRET-GROQ")
    runner=MagicMock(return_value={
        "status":"success","content":"{\"flashcards\":[]}",
        "metadata":{"response_length":17,"done_reason":"stop"},
    })
    provider=DeepTutorProvider(config(
        "groq",model="qwen/qwen3.8-27b",allow_cloud_document_content=True),tmp_path,runner)
    result=await provider.generate("document",response_format={"type":"json_object"},
                                   timeout_seconds=30)
    request,timeout=runner.call_args.args
    assert request["response_format"]=={"type":"json_object"}
    assert request["timeout_seconds"]==30 and timeout==30
    assert "SECRET-GROQ" not in repr(request)+repr(result)
    assert result.metadata=={"response_length":17,"done_reason":"stop"}
