from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService


class MoodleIngestionInput(BaseModel):
    course_id_moodle: int = Field(gt=0)
    resource_id: int = Field(gt=0)
    kb_name: str | None = Field(default=None, min_length=1, max_length=120)


def create_moodle_ingestion_router(
    moodle_adapter: Any | None,
    deeptutor_service: DeepTutorService,
) -> APIRouter:
    router = APIRouter(tags=["moodle-ingestion"])

    @router.post("/moodle/resources/ingest")
    def ingest_moodle_resource(request: MoodleIngestionInput) -> dict[str, Any]:
        if moodle_adapter is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "moodle_unavailable", "message": "Moodle is not configured."},
            )
        try:
            normalized_doc, pdf_bytes = moodle_adapter.get_normalized_document(
                request.course_id_moodle, request.resource_id
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "moodle_document_unavailable", "message": "Unable to retrieve Moodle document."},
            ) from exc
        try:
            return deeptutor_service.ingest_moodle_document(
                normalized_doc, pdf_bytes, kb_id=request.kb_name
            )
        except DeepTutorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc

    return router
