import time
import logging
import httpx
from typing import Optional, Dict, Any
from backend.services.ai.provider_base import LLMProvider, LLMResult

logger = logging.getLogger(__name__)

class DeepSeekProvider(LLMProvider):
    provider = "deepseek"

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str = "https://api.deepseek.com/v1", timeout_seconds: float = 30.0):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("API key không được để trống cho DeepSeekProvider.")
        self.api_key = api_key.strip()
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    async def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs: Any) -> LLMResult:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            **kwargs
        }

        start_time = time.time()
        attempt = 0
        max_retries = 1
        last_exception = None

        while attempt <= max_retries:
            attempt += 1
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                    
                    latency_ms = (time.time() - start_time) * 1000

                    if response.status_code == 200:
                        data = response.json()
                        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                        usage = data.get("usage", {})
                        return LLMResult(
                            status="success",
                            provider="deepseek",
                            model=self.model,
                            content=content,
                            latency_ms=latency_ms,
                            usage=usage,
                            error_code=None,
                            fallback_used=False
                        )
                    elif response.status_code in [429, 500, 502, 503, 504]:
                        # Transient errors - có thể retry nếu còn lượt
                        if attempt <= max_retries:
                            continue
                        return LLMResult(
                            status="error",
                            provider="deepseek",
                            model=self.model,
                            content="",
                            latency_ms=latency_ms,
                            error_code=f"HTTP_{response.status_code}",
                            fallback_used=False
                        )
                    else:
                        # Lỗi client (400, 401, v.v.) không retry
                        return LLMResult(
                            status="error",
                            provider="deepseek",
                            model=self.model,
                            content="",
                            latency_ms=latency_ms,
                            error_code=f"HTTP_{response.status_code}",
                            fallback_used=False
                        )
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt <= max_retries:
                    continue
                latency_ms = (time.time() - start_time) * 1000
                return LLMResult(
                    status="error",
                    provider="deepseek",
                    model=self.model,
                    content="",
                    latency_ms=latency_ms,
                    error_code="TIMEOUT_OR_NETWORK_ERROR",
                    fallback_used=False
                )
            except Exception as e:
                latency_ms = (time.time() - start_time) * 1000
                logger.error("Lỗi không xác định khi gọi DeepSeek provider")
                return LLMResult(
                    status="error",
                    provider="deepseek",
                    model=self.model,
                    content="",
                    latency_ms=latency_ms,
                    error_code="UNKNOWN_ERROR",
                    fallback_used=False
                )

        latency_ms = (time.time() - start_time) * 1000
        return LLMResult(
            status="error",
            provider="deepseek",
            model=self.model,
            content="",
            latency_ms=latency_ms,
            error_code="MAX_RETRIES_EXCEEDED",
            fallback_used=False
        )

    async def health_check(self) -> Dict[str, Any]:
        return {
            "provider": "deepseek",
            "model": self.model,
            "status": "available" if self.api_key else "unconfigured"
        }
