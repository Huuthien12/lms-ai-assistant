import time
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
        options = dict(kwargs.pop("options", {}) or {})
        for key in ("temperature", "top_p", "seed"):
            if key in kwargs:
                options[key] = kwargs.pop(key)
        if "max_tokens" in kwargs:
            options["num_predict"] = kwargs.pop("max_tokens")
        payload = {**kwargs, "options": options, "model": self.model,
                   "messages": messages, "stream": False}
        code = "UNKNOWN_ERROR"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
            if response.status_code != 200:
                code = f"HTTP_{response.status_code}"
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
                    return LLMResult("success", self.provider, self.model,
                                     data["message"]["content"],
                                     (time.monotonic() - start) * 1000, usage=usage)
        except (httpx.TimeoutException, httpx.NetworkError):
            code = "TIMEOUT_OR_NETWORK_ERROR"
        except (ValueError, TypeError, KeyError):
            code = "INVALID_RESPONSE"
        except Exception:
            code = "UNKNOWN_ERROR"
        return LLMResult("error", self.provider, self.model, "",
                         (time.monotonic() - start) * 1000, error_code=code)

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
