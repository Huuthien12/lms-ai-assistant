import time
from typing import Any, Dict, Optional

import httpx

from backend.services.ai.provider_base import LLMProvider, LLMResult


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str = "qwen2.5:3b",
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 60.0,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": self.model, "messages": messages, "stream": False, **kwargs},
                )
            latency_ms = (time.perf_counter() - started) * 1000
            if response.status_code != 200:
                return LLMResult(
                    status="error", provider="ollama", model=self.model, content="",
                    latency_ms=latency_ms, error_code=f"HTTP_{response.status_code}",
                )
            data = response.json()
            content = data.get("message", {}).get("content", "")
            return LLMResult(
                status="success", provider="ollama", model=self.model, content=content,
                latency_ms=latency_ms, usage={"total_tokens": data.get("eval_count", 0)},
            )
        except (httpx.TimeoutException, httpx.NetworkError):
            return LLMResult(
                status="error", provider="ollama", model=self.model, content="",
                latency_ms=(time.perf_counter() - started) * 1000,
                error_code="TIMEOUT_OR_NETWORK_ERROR",
            )
        except Exception:
            return LLMResult(
                status="error", provider="ollama", model=self.model, content="",
                latency_ms=(time.perf_counter() - started) * 1000, error_code="UNKNOWN_ERROR",
            )

    async def health_check(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            return {"provider": "ollama", "model": self.model, "status": "available" if response.status_code == 200 else "unavailable"}
        except (httpx.TimeoutException, httpx.NetworkError):
            return {"provider": "ollama", "model": self.model, "status": "unavailable"}
