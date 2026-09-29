from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai.grounded_chat import (
    GroundedChatRequest,
    GroundedChatService,
    RetrievedContextItem,
)
from deeptutor_integration.contracts import QueryInput
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService


class GroundedChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    course_id: str = Field(min_length=1, max_length=120)
    kb_name: str | None = Field(default=None, min_length=1, max_length=120)


def retrieved_contexts(result: Mapping[str, Any]) -> list[RetrievedContextItem]:
    """Map the verified DeepTutor CLI source shape without using generated output."""
    sources = result.get("sources")
    if not isinstance(sources, list):
        return []

    contexts: list[RetrievedContextItem] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        content = source.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        metadata = {
            key: source[key]
            for key in ("source", "page")
            if key in source and source[key] not in (None, "")
        }
        score = source.get("score")
        contexts.append(
            RetrievedContextItem(
                text=content,
                source_id=source.get("chunk_id") if isinstance(source.get("chunk_id"), str) else None,
                title=source.get("title") if isinstance(source.get("title"), str) else None,
                score=float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None,
                metadata=metadata,
            )
        )
    return contexts


def create_grounded_chat_router(
    deeptutor_service: DeepTutorService,
    grounded_chat_service: GroundedChatService | None,
) -> APIRouter:
    router = APIRouter(tags=["grounded-chat"])

    @router.post("/chat/grounded")
    async def grounded_chat(request: GroundedChatInput) -> dict[str, Any]:
        if grounded_chat_service is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "ai_unavailable", "message": "AI provider is not configured."},
            )
        try:
            kb_name = deeptutor_service.kb_name(request.course_id, request.kb_name)
            query_result = deeptutor_service.query(
                QueryInput(course_id=request.course_id, question=request.question, kb_id=kb_name)
            )
        except DeepTutorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc

        try:
            response = await grounded_chat_service.chat(
                GroundedChatRequest(
                    query=request.question,
                    contexts=retrieved_contexts(query_result["result"]),
                    course_id=query_result["course_id"],
                    kb_name=query_result["kb_id"],
                )
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "ai_provider_failure", "message": "AI provider could not generate a response."},
            ) from exc
        return asdict(response)

    return router
