from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
from collections.abc import Callable
from typing import Any

from backend.services.ai.model_config import ModelConfig
from backend.services.ai.provider_base import LLMProvider, LLMResult


class DeepTutorProvider(LLMProvider):
    """Thin bridge to DeepTutor's provider registry and SDK adapters."""

    def __init__(self, config: ModelConfig, deeptutor_dir: Path,
                 runner: Callable[[dict[str, Any], float], dict[str, Any]] | None = None):
        self.config = config
        self.provider = config.provider
        self.model = config.model
        self.deeptutor_dir = deeptutor_dir.resolve()
        self.python = self.deeptutor_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        self._runner = runner or self._run_worker

    def _run_worker(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        if not self.python.is_file():
            raise OSError("DeepTutor runtime is unavailable")
        worker = Path(__file__).with_name("deeptutor_llm_worker.py")
        environment = os.environ.copy()
        environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                           PYTHONPATH=str(self.deeptutor_dir))
        result = subprocess.run(
            [str(self.python), str(worker)], cwd=self.deeptutor_dir, env=environment,
            input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True,
            encoding="utf-8", timeout=timeout, shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        data = json.loads(result.stdout)
        if result.returncode or not isinstance(data, dict):
            raise ValueError("invalid worker response")
        return data

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> LLMResult:
        started = time.monotonic()
        if self.config.is_cloud and not self.config.allow_cloud_document_content:
            return LLMResult("error", self.provider, self.model, "", 0,
                             error_code="CLOUD_CONTENT_DISABLED")
        if self.config.api_key_env and not os.getenv(self.config.api_key_env, "").strip():
            return LLMResult("error", self.provider, self.model, "", 0,
                             error_code="PROVIDER_UNCONFIGURED")
        try:
            request_timeout=min(self.config.timeout_seconds,
                                float(kwargs.get("timeout_seconds",self.config.timeout_seconds)))
            if request_timeout <= 0: raise ValueError()
        except (TypeError,ValueError):
            return LLMResult("error",self.provider,self.model,"",0,error_code="INVALID_REQUEST")
        request = {
            "provider": self.provider,
            "model": self.model,
            "prompt": prompt,
            "system_prompt": system_prompt,
            "temperature": kwargs.get("temperature", self.config.temperature),
            "max_tokens": kwargs.get("max_tokens", self.config.max_tokens),
            "api_key_env": self.config.api_key_env,
            "base_url": self.config.base_url,
            "timeout_seconds": request_timeout,
        }
        if isinstance(kwargs.get("response_format"),dict):
            request["response_format"]=kwargs["response_format"]
        code = "UNKNOWN_ERROR"
        try:
            data = await asyncio.wait_for(
                asyncio.to_thread(self._runner, request, request_timeout),
                timeout=request_timeout + 1,
            )
        except (TimeoutError, subprocess.TimeoutExpired, OSError):
            code, data = "TIMEOUT_OR_NETWORK_ERROR", None
        except (ValueError, TypeError, json.JSONDecodeError):
            code, data = "INVALID_RESPONSE", None
        except Exception:
            code, data = "UNKNOWN_ERROR", None
        if isinstance(data, dict) and data.get("status") == "success" and isinstance(data.get("content"), str):
            usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
            return LLMResult("success", self.provider, self.model, data["content"],
                             (time.monotonic() - started) * 1000, usage=usage,
                             metadata=data.get("metadata") if isinstance(data.get("metadata"),dict) else {})
        if isinstance(data, dict):
            code = data.get("error_code") if isinstance(data.get("error_code"), str) else "UNKNOWN_ERROR"
        return LLMResult("error", self.provider, self.model, "",
                         (time.monotonic() - started) * 1000, error_code=code,
                         metadata=data.get("metadata") if isinstance(data,dict)
                         and isinstance(data.get("metadata"),dict) else {})

    async def health_check(self) -> dict[str, Any]:
        configured = not self.config.api_key_env or bool(os.getenv(self.config.api_key_env, "").strip())
        return {"provider": self.provider, "model": self.model,
                "status": "available" if configured else "unconfigured"}
