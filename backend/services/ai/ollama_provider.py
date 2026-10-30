import json
import time
from collections.abc import Mapping
from typing import Any, Dict, Optional

import httpx

from backend.services.ai.provider_base import LLMProvider, LLMResult


class OllamaProvider(LLMProvider):
    provider = "ollama"

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "qwen2.5:3b", timeout_seconds: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       **kwargs: Any) -> LLMResult:
        start = time.monotonic()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        # Runtime sampling settings belong in Ollama's options object.
        try:
            request_timeout = float(kwargs.pop("timeout_seconds", self.timeout_seconds))
            if request_timeout <= 0:
                raise ValueError("invalid timeout")
            supplied_options = kwargs.pop("options", {})
            if not isinstance(supplied_options, Mapping):
                raise ValueError("invalid options")
            response_format = kwargs.pop("response_format", None)
            if response_format not in (None, {"type": "json_object"}):
                raise ValueError("invalid response format")
            options = dict(supplied_options)
            for key in ("temperature", "top_p", "seed"):
                if key in kwargs:
                    options[key] = kwargs.pop(key)
            if "max_tokens" in kwargs:
                options["num_predict"] = kwargs.pop("max_tokens")
            payload = {**kwargs, "options": options, "model": self.model,
                       "messages": messages, "stream": False}
            if response_format is not None:
                payload["format"] = "json"
        except Exception:
            return LLMResult("error", self.provider, self.model, "",
                             (time.monotonic() - start) * 1000,
                             error_code="INVALID_REQUEST")
        code, metadata = "UNKNOWN_ERROR", {}
        try:
            async with httpx.AsyncClient(timeout=min(self.timeout_seconds, request_timeout)) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code != 200:
                code = f"HTTP_{response.status_code}"
                metadata = {"provider_http_status":response.status_code}
            else:
                data = response.json()
                if (not isinstance(data, dict) or data.get("done") is False
                        or not isinstance(data.get("message"), dict)
                        or not isinstance(data["message"].get("content"), str)
                        or not data["message"]["content"].strip()):
                    code = "INVALID_RESPONSE"
                else:
                    usage = {}
                    for source, target in (("prompt_eval_count", "prompt_tokens"),
                                           ("eval_count", "completion_tokens")):
                        value = data.get(source)
                        if type(value) is int and value >= 0:
                            usage[target] = value
                    if len(usage) == 2:
                        usage["total_tokens"] = sum(usage.values())
                    content=data["message"]["content"]
                    try:
                        parsed=json.loads(content)
                        parse_category="object" if isinstance(parsed,dict) else "non_object"
                        top_level_keys=(sorted(key for key in parsed if isinstance(key,str))
                                        if isinstance(parsed,dict) else [])
                    except (ValueError,TypeError):
                        parse_category,top_level_keys="invalid_json",[]
                    return LLMResult("success", self.provider, self.model,
                                     content,(time.monotonic() - start) * 1000, usage=usage,
                                     metadata={"response_length":len(content),
                                               "json_parse_category":parse_category,
                                               "top_level_keys":top_level_keys,
                                               "done_reason":data.get("done_reason"),
                                               "completion_tokens":data.get("eval_count")})
        except (httpx.TimeoutException, httpx.NetworkError):
            code = "TIMEOUT_OR_NETWORK_ERROR"
        except (ValueError, TypeError, KeyError):
            code = "INVALID_RESPONSE"
        except Exception:
            code = "UNKNOWN_ERROR"
        return LLMResult("error", self.provider, self.model, "",
                         (time.monotonic() - start) * 1000, error_code=code,
                         metadata=metadata)

    async def health_check(self) -> Dict[str, Any]:
        status = "unavailable"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            if response.status_code == 200:
                models = response.json().get("models")
                if isinstance(models, list) and any(
                    isinstance(item, dict) and item.get("name") == self.model
                    for item in models
                ):
                    status = "available"
        except Exception:
            pass
        return {"provider": self.provider, "model": self.model, "status": status}
