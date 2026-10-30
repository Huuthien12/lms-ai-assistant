"""JSON stdin/stdout bridge into DeepTutor's existing provider factory."""

import asyncio
import contextlib
import io
import json
import os
import sys
import urllib.error
import urllib.request


def _safe_response_value(value, limit=128):
    if not isinstance(value, str) or not value or len(value) > limit:
        return None
    return value if all(character.isalnum() or character in "._:-/" for character in value) else None


def _response_diagnostics(body, http_status, choice=None, message=None, content=...):
    metadata = {}
    if isinstance(http_status, int) and not isinstance(http_status, bool):
        metadata["http_status"] = http_status
    if isinstance(body, dict):
        response_id = _safe_response_value(body.get("id"))
        if response_id is not None:
            metadata["provider_response_id"] = response_id
    if isinstance(choice, dict):
        for source, target in (("finish_reason", "finish_reason"),
                               ("native_finish_reason", "native_finish_reason")):
            value = _safe_response_value(choice.get(source))
            if value is not None:
                metadata[target] = value
    if content is not ...:
        metadata["content_type"] = type(content).__name__
        if content is None:
            metadata["content_length"] = 0
        elif isinstance(content, (str, list, tuple)):
            metadata["content_length"] = len(content)
    if isinstance(message, dict):
        reasoning = message.get("reasoning")
        metadata["reasoning_present"] = bool(reasoning)
        if reasoning is None:
            metadata["reasoning_length"] = 0
        elif isinstance(reasoning, (str, list, tuple)):
            metadata["reasoning_length"] = len(reasoning)
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        for key in ("prompt_tokens", "completion_tokens"):
            value = usage.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                metadata[key] = value
        details = usage.get("completion_tokens_details")
        reasoning_tokens = details.get("reasoning_tokens") if isinstance(details, dict) else usage.get("reasoning_tokens")
        if isinstance(reasoning_tokens, int) and not isinstance(reasoning_tokens, bool) and reasoning_tokens >= 0:
            metadata["reasoning_tokens"] = reasoning_tokens
    return metadata


def _openai_compatible(request):
    """Groq/OpenRouter chat completions, without changing DeepTutor's provider registry."""

    endpoints = {
        "groq": "https://api.groq.com/openai/v1",
        "openrouter": "https://openrouter.ai/api/v1",
    }

    name = request["provider"]

    key_env = {
        "groq": "GROQ_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }[name]

    if request.get("api_key_env") != key_env:
        return {
            "status": "error",
            "error_code": "INVALID_API_KEY_CONFIG",
        }

    key = os.getenv(key_env, "").strip()

    if not key:
        return {
            "status": "error",
            "error_code": "PROVIDER_UNCONFIGURED",
        }

    # Fixed trusted endpoints. Never send API keys to user-controlled URLs.
    endpoint = endpoints[name] + "/chat/completions"

    messages = []

    if request.get("system_prompt"):
        messages.append({
            "role": "system",
            "content": request["system_prompt"],
        })

    messages.append({
        "role": "user",
        "content": request["prompt"],
    })

    payload = {
        "model": request["model"],
        "messages": messages,
        "temperature": float(request["temperature"]),
        "max_tokens": int(request["max_tokens"]),
        "stream": False,
    }
    response_format=request.get("response_format")
    if response_format is not None:
        if response_format != {"type":"json_object"}:
            return {"status":"error","error_code":"INVALID_REQUEST"}
        payload["response_format"]=response_format

    data = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    # FIX: Define headers before creating the HTTP request.
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "DeepTutor-Benchmark/1.0",
    }

    req = urllib.request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )

    http_status = None
    try:
        with urllib.request.urlopen(req, timeout=float(request.get("timeout_seconds",100))) as response:
            http_status = getattr(response, "status", None)
            if not isinstance(http_status, int):
                getcode = getattr(response, "getcode", None)
                http_status = getcode() if callable(getcode) else None
            body = json.load(response)

    except urllib.error.HTTPError as error:
        status = error.code
        retry_after=error.headers.get("Retry-After") if error.headers else None
        try: retry_after=float(retry_after) if retry_after is not None else None
        except (TypeError,ValueError): retry_after=None

        return {
            "status": "error",
            "error_code": f"HTTP_{status}",
            "metadata":{"provider_http_status":status,
                        **({"retry_after_seconds":retry_after} if retry_after is not None else {})},
        }

    except (urllib.error.URLError, TimeoutError):
        return {
            "status": "error",
            "error_code": "TIMEOUT_OR_NETWORK_ERROR",
        }

    try:
        choice = body["choices"][0]
        message = choice["message"]
        content = message["content"]

        if not isinstance(content, str) or not content.strip():
            return {
                "status": "error",
                "error_code": "EMPTY_RESPONSE",
                "metadata": _response_diagnostics(body, http_status, choice, message, content),
            }

        usage = body.get("usage")
        finish_reason=body["choices"][0].get("finish_reason")
        try:
            parsed=json.loads(content)
            parse_category="object" if isinstance(parsed,dict) else "non_object"
            keys=sorted(key for key in parsed if isinstance(key,str)) if isinstance(parsed,dict) else []
        except (ValueError,TypeError):
            parse_category,keys="invalid_json",[]

        return {
            "status": "success",
            "content": content,
            "usage": usage if isinstance(usage, dict) else {},
            "metadata":{"response_length":len(content),"json_parse_category":parse_category,
                        "top_level_keys":keys,"done_reason":finish_reason,
                        "completion_tokens":usage.get("completion_tokens") if isinstance(usage,dict) else None},
        }

    except (KeyError, IndexError, TypeError):
        return {
            "status": "error",
            "error_code": "INVALID_RESPONSE",
            "metadata": _response_diagnostics(body, http_status),
        }


async def execute(request):
    # Groq and OpenRouter use OpenAI-compatible HTTP APIs.
    if request.get("provider") in {"groq", "openrouter"}:
        return await asyncio.to_thread(
            _openai_compatible,
            request,
        )

    # Existing DeepTutor providers remain unchanged.
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.llm.provider_factory import get_runtime_provider
    from deeptutor.services.provider_registry import find_by_name

    name = request["provider"]

    if name not in {"ollama", "openai", "gemini", "anthropic"}:
        raise ValueError("unsupported provider")

    spec = find_by_name(name)

    key_name = request.get("api_key_env")

    api_key = (
        os.getenv(key_name, "")
        if isinstance(key_name, str)
        else ""
    )

    base_url = request.get("base_url") or (
        spec.default_api_base if spec else None
    )

    config = LLMConfig(
        model=request["model"],
        api_key=api_key or "sk-no-key-required",
        base_url=base_url,
        effective_url=base_url,
        binding=name,
        provider_name=name,
        temperature=float(request["temperature"]),
        max_tokens=int(request["max_tokens"]),
    )

    provider = get_runtime_provider(config)

    messages = []

    if request.get("system_prompt"):
        messages.append({
            "role": "system",
            "content": request["system_prompt"],
        })

    messages.append({
        "role": "user",
        "content": request["prompt"],
    })

    response = await provider.chat_with_retry(
        messages=messages,
        model=request["model"],
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        retry_delays=(),
    )

    if (
        response.finish_reason == "error"
        or not isinstance(response.content, str)
        or not response.content.strip()
    ):
        return {
            "status": "error",
            "error_code": "PROVIDER_ERROR",
        }

    return {
        "status": "success",
        "content": response.content,
        "usage": response.usage,
    }


if __name__ == "__main__":
    try:
        request = json.loads(sys.stdin.read())

        with (
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            result = asyncio.run(execute(request))

        encoded = json.dumps(
            result,
            ensure_ascii=False,
            allow_nan=False,
        )

    except Exception:
        encoded = json.dumps({
            "status": "error",
            "error_code": "PROVIDER_ERROR",
        })

    print(encoded)
