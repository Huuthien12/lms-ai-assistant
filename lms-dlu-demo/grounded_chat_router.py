from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict
import json
from pathlib import Path
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

from backend.services.ai.grounded_chat import (
    GroundedChatRequest,
    GroundedChatResponse,
    GroundedChatService,
    RetrievedContextItem,
)
from deeptutor_integration.contracts import QueryInput
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger


class GroundedChatInput(BaseModel):
    question: str = Field(min_length=1, max_length=8000)
    course_id: str = Field(min_length=1, max_length=120)
    kb_name: str | None = Field(default=None, min_length=1, max_length=120)

    @field_validator("question", "course_id", "kb_name")
    @classmethod
    def strip_nonblank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Value must not be blank.")
        return value


def validate_retrieval(envelope: Any, course_id: str) -> Mapping[str, Any]:
    """Validate the public envelope and explicit scope, without resolving KBs.

    Absent source identities remain an upstream ownership guarantee.
    """
    if not isinstance(envelope, Mapping):
        raise ValueError("invalid retrieval")
    returned_course, kb_id = envelope.get("course_id"), envelope.get("kb_id")
    result = envelope.get("result")
    if (not isinstance(returned_course, str) or not returned_course.strip()
            or returned_course != course_id or not isinstance(kb_id, str)
            or not kb_id.strip() or not isinstance(result, Mapping)):
        raise ValueError("invalid retrieval")
    if "sources" in result and not isinstance(result["sources"], list):
        raise ValueError("invalid retrieval")
    for source in result.get("sources", []):
        if not isinstance(source, Mapping):
            continue
        metadata = source.get("metadata")
        for identity in (source, metadata if isinstance(metadata, Mapping) else {}):
            for key, expected in (("course_id", course_id), ("kb_id", kb_id), ("kb_name", kb_id)):
                if key in identity and identity[key] != expected:
                    raise ValueError("invalid source scope")
    return result


def retrieved_contexts(result: Mapping[str, Any], ledger: MoodleIngestionLedger | None = None, course_id: str = "") -> list[RetrievedContextItem]:
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
        source_metadata = source.get("metadata")
        provenance = source_metadata if isinstance(source_metadata, Mapping) else {}
        metadata = {
            key: source[key]
            for key in ("page", "slide", "section")
            if key in source and source[key] not in (None, "")
        }
        original_filename = source.get("original_filename") or provenance.get("original_filename")
        if not original_filename and ledger and isinstance(source.get("title"), str):
            match = re.fullmatch(r"(\d+)-([0-9a-f]{64})\.md", source["title"])
            if match:
                original_filename = ledger.original_filename(course_id, match.group(1), match.group(2))
        score = source.get("score")
        contexts.append(
            RetrievedContextItem(
                text=content,
                source_id=source.get("chunk_id") if isinstance(source.get("chunk_id"), str) else None,
                title=original_filename if isinstance(original_filename, str) and original_filename else (
                    source.get("title") if isinstance(source.get("title"), str) else None
                ),
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
    config = getattr(deeptutor_service, "config", None)
    ledger = MoodleIngestionLedger(config.runtime_dir) if config else None

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
        except Exception:
            raise HTTPException(502, detail={
                "code": "retrieval_failure", "message": "Retrieval could not be completed.",
            }) from None

        try:
            result = validate_retrieval(query_result, request.course_id)
            contexts = retrieved_contexts(result, ledger, request.course_id)
        except Exception:
            raise HTTPException(502, detail={
                "code": "invalid_retrieval_response", "message": "Retrieval returned an invalid response.",
            }) from None

        try:
            response = await grounded_chat_service.chat(
                GroundedChatRequest(
                    query=request.question,
                    contexts=contexts,
                    course_id=query_result["course_id"],
                    kb_name=query_result["kb_id"],
                )
            )
            if not isinstance(response, GroundedChatResponse):
                raise ValueError("invalid chat response")
            if (response.status not in ("success", "error") or not isinstance(response.answer, str)
                    or response.course_id != request.course_id or response.kb_name != query_result["kb_id"]
                    or not isinstance(response.sources, list)
                    or not all(isinstance(source, dict) for source in response.sources)
                    or not isinstance(response.ai, dict)
                    or not isinstance(response.ai.get("provider"), str)
                    or not isinstance(response.ai.get("model"), str)
                    or type(response.ai.get("fallback_used")) is not bool):
                raise ValueError("invalid chat response")
            payload = asdict(response)
            json.dumps(payload, allow_nan=False)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "ai_provider_failure", "message": "AI provider could not generate a response."},
            ) from None
        return payload

    return router
