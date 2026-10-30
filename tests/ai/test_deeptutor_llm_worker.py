import io
import json
import urllib.error

import pytest

from backend.services.ai import deeptutor_llm_worker as worker


def request():
    return {
        "provider":"groq","model":"qwen/qwen3.8-27b","prompt":"document",
        "system_prompt":"return JSON","temperature":0.1,"max_tokens":1536,
        "api_key_env":"GROQ_API_KEY","response_format":{"type":"json_object"},
        "timeout_seconds":30,
    }


class Response(io.BytesIO):
    status = 200


def test_groq_worker_maps_json_mode_and_safe_response_metadata(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","SECRET-GROQ")
    captured={}
    def urlopen(req,timeout):
        captured["request"],captured["timeout"]=req,timeout
        return Response(json.dumps({
            "choices":[{"message":{"content":"{\"flashcards\":[]}"},"finish_reason":"stop"}],
            "usage":{"prompt_tokens":10,"completion_tokens":4},
        }).encode())
    monkeypatch.setattr(worker.urllib.request,"urlopen",urlopen)
    result=worker._openai_compatible(request())
    payload=json.loads(captured["request"].data)
    assert payload["response_format"]=={"type":"json_object"}
    assert payload["stream"] is False and captured["timeout"]==30
    assert "SECRET-GROQ" not in json.dumps(payload)+repr(result)
    assert result["metadata"]=={
        "response_length":17,"json_parse_category":"object",
        "top_level_keys":["flashcards"],"done_reason":"stop","completion_tokens":4,
    }


def test_openrouter_empty_content_keeps_safe_diagnostics(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET-OPENROUTER")
    value = request(); value.update(provider="openrouter", api_key_env="OPENROUTER_API_KEY")
    body = {
        "id": "gen-123",
        "choices": [{"message": {"content": "", "reasoning": "PRIVATE REASONING"},
                     "finish_reason": "length", "native_finish_reason": "max_tokens"}],
        "usage": {"prompt_tokens": 1400, "completion_tokens": 1024,
                  "completion_tokens_details": {"reasoning_tokens": 1024}},
    }
    monkeypatch.setattr(worker.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(json.dumps(body).encode()))
    result = worker._openai_compatible(value)
    assert result == {"status": "error", "error_code": "EMPTY_RESPONSE", "metadata": {
        "http_status": 200, "provider_response_id": "gen-123", "finish_reason": "length",
        "native_finish_reason": "max_tokens", "content_type": "str", "content_length": 0,
        "reasoning_present": True, "reasoning_length": 17, "prompt_tokens": 1400,
        "completion_tokens": 1024, "reasoning_tokens": 1024,
    }}
    assert "PRIVATE" not in repr(result)


@pytest.mark.parametrize(("content", "reasoning", "content_type", "content_length", "reasoning_present"), [
    (None, "PRIVATE REASONING", "NoneType", 0, True),
    ([{"type": "text", "text": "PRIVATE"}], None, "list", 1, False),
])
def test_openrouter_null_and_multipart_content_remain_empty_response(
        monkeypatch, content, reasoning, content_type, content_length, reasoning_present):
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET-OPENROUTER")
    value = request(); value.update(provider="openrouter", api_key_env="OPENROUTER_API_KEY")
    body = {"choices": [{"message": {"content": content, "reasoning": reasoning},
                          "finish_reason": "stop"}]}
    monkeypatch.setattr(worker.urllib.request, "urlopen",
                        lambda *args, **kwargs: Response(json.dumps(body).encode()))
    result = worker._openai_compatible(value)
    assert result["error_code"] == "EMPTY_RESPONSE"
    assert result["metadata"]["content_type"] == content_type
    assert result["metadata"]["content_length"] == content_length
    assert result["metadata"]["reasoning_present"] is reasoning_present
    assert "PRIVATE" not in repr(result)


def test_http_200_error_object_remains_invalid_response_without_body(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "SECRET-OPENROUTER")
    value = request(); value.update(provider="openrouter", api_key_env="OPENROUTER_API_KEY")
    monkeypatch.setattr(worker.urllib.request, "urlopen", lambda *args, **kwargs: Response(
        json.dumps({"id": "gen-error", "error": {"message": "PRIVATE ERROR"}}).encode()))
    result = worker._openai_compatible(value)
    assert result == {"status": "error", "error_code": "INVALID_RESPONSE",
                      "metadata": {"http_status": 200, "provider_response_id": "gen-error"}}
    assert "PRIVATE" not in repr(result)


def test_groq_worker_reports_http_status_without_response_body(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","SECRET-GROQ")
    def fail(*args,**kwargs):
        raise urllib.error.HTTPError("https://api.groq.com",500,"PRIVATE",{"Retry-After":"12"},None)
    monkeypatch.setattr(worker.urllib.request,"urlopen",fail)
    result=worker._openai_compatible(request())
    assert result=={"status":"error","error_code":"HTTP_500",
                   "metadata":{"provider_http_status":500,"retry_after_seconds":12.0}}
    assert "PRIVATE" not in repr(result)


def test_groq_worker_reports_timeout_and_rejects_unsupported_format(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY","SECRET-GROQ")
    monkeypatch.setattr(worker.urllib.request,"urlopen",
                        lambda *args,**kwargs: (_ for _ in ()).throw(TimeoutError()))
    assert worker._openai_compatible(request())["error_code"]=="TIMEOUT_OR_NETWORK_ERROR"
    invalid=request(); invalid["response_format"]={"type":"json_schema"}
    assert worker._openai_compatible(invalid)["error_code"]=="INVALID_REQUEST"
