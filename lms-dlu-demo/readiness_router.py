from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter

from deeptutor_integration.service import DeepTutorService


def create_readiness_router(
    deeptutor_service: DeepTutorService,
    ollama_provider: Any,
    moodle_adapter: Any | None,
) -> APIRouter:
    router = APIRouter(tags=["health"])

    @router.get("/health/ready")
    async def readiness() -> dict[str, Any]:
        try:
            deeptutor = deeptutor_service.health().get("status", "unavailable")
        except Exception:
            deeptutor = "unavailable"
        try:
            resolver = "available" if deeptutor_service.kb_name("INT1339") == "int1339-python" else "unavailable"
        except Exception:
            resolver = "unavailable"
        try:
            ollama_health = await ollama_provider.health_check()
            ollama = ollama_health.get("status", "unavailable") if isinstance(ollama_health, Mapping) else "unavailable"
        except Exception:
            ollama = "unavailable"
        moodle = "configured" if moodle_adapter is not None else "unconfigured"
        components = {
            "deeptutor": deeptutor,
            "course_kb": resolver,
            "ollama": ollama,
            "moodle": moodle,
        }
        return {
            "status": "ready" if components == {
                "deeptutor": "available", "course_kb": "available",
                "ollama": "available", "moodle": "configured",
            } else "degraded",
            "components": components,
        }

    return router
