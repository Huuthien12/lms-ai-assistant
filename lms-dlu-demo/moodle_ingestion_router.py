from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor_integration.contracts import DocumentInput, NormalizedDocument
from deeptutor_integration.document_normalizer import DocumentNormalizer
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger
from deeptutor_integration.service import DeepTutorService
from moodle_service_auth import create_moodle_service_dependency


class MoodleIngestionInput(BaseModel):
    course_id_moodle: int = Field(gt=0)
    resource_id: int = Field(gt=0)
    kb_name: str | None = Field(default=None, min_length=1, max_length=120)


def create_moodle_ingestion_router(
    moodle_adapter: Any | None,
    deeptutor_service: DeepTutorService,
    normalizer: DocumentNormalizer | None = None,
    ledger: MoodleIngestionLedger | None = None,
    service_token: str | None = None,
) -> APIRouter:
    router = APIRouter(tags=["moodle-ingestion"])
    normalizer = normalizer or DocumentNormalizer()
    ledger = ledger or MoodleIngestionLedger(deeptutor_service.config.runtime_dir)

    require_configured_moodle_service = create_moodle_service_dependency(
        os.getenv("LMS_MOODLE_DISCOVERY_TOKEN") if service_token is None else service_token
    )

    @router.get("/moodle/courses", dependencies=[Depends(require_configured_moodle_service)])
    def list_moodle_courses() -> list[dict[str, Any]]:
        if moodle_adapter is None:
            raise HTTPException(status_code=503, detail={"code": "moodle_unavailable", "message": "Moodle is not configured."})
        try:
            return moodle_adapter.list_courses()
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"code": "moodle_discovery_unavailable", "message": "Unable to retrieve Moodle courses."}) from exc

    @router.get("/moodle/courses/{course_id_moodle}/resources", dependencies=[Depends(require_configured_moodle_service)])
    def list_moodle_resources(course_id_moodle: int) -> list[dict[str, Any]]:
        if moodle_adapter is None:
            raise HTTPException(status_code=503, detail={"code": "moodle_unavailable", "message": "Moodle is not configured."})
        try:
            course = moodle_adapter.get_course(course_id_moodle)
            kb_id = deeptutor_service.kb_name(course["shortname"])
            statuses = {"ACTIVE": "indexed", "SUPERSEDED": "superseded", "DELETED": "deleted"}
            return [{**resource, "sync_status": statuses.get(ledger.resource_lifecycle(course["shortname"], str(resource["resource_id"])), "not_synced"), "kb_id": kb_id} for resource in moodle_adapter.list_file_resources(course_id_moodle)]
        except DeepTutorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"code": "moodle_discovery_unavailable", "message": "Unable to retrieve Moodle resources."}) from exc

    def document_input(document: NormalizedDocument, kb_id: str | None) -> DocumentInput:
        return DocumentInput(
            document_id=document.document_id,
            course_id=document.course_id,
            filename=f"{document.document_id}-{document.sha256}.md",
            mime_type="text/markdown",
            source=document.source,
            metadata={
                **document.metadata,
                "course_id": document.course_id,
                "document_id": document.document_id,
                "source": document.source,
                "original_filename": document.original_filename,
                "original_mime_type": document.original_mime_type,
                "original_sha256": document.sha256,
                "source_sha256": document.sha256,
                "normalizer_version": document.normalizer_version,
            },
            content=document.markdown,
            kb_id=kb_id,
        )

    @router.post("/moodle/resources/ingest", dependencies=[Depends(require_configured_moodle_service)])
    def ingest_moodle_resource(request: MoodleIngestionInput) -> dict[str, Any]:
        if moodle_adapter is None:
            raise HTTPException(
                status_code=503,
                detail={"code": "moodle_unavailable", "message": "Moodle is not configured."},
            )
        try:
            source = moodle_adapter.get_source_document(request.course_id_moodle, request.resource_id)
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "moodle_document_unavailable", "message": "Unable to retrieve Moodle document."},
            ) from exc
        try:
            normalized = normalizer.normalize(source)
            kb_id = deeptutor_service.kb_name(normalized.course_id, request.kb_name)
            if ledger.contains(normalized):
                return {
                    "document_id": normalized.document_id,
                    "course_id": normalized.course_id,
                    "kb_id": kb_id,
                    "action": "deduplicated",
                    "status": "already_indexed",
                    "deduplicated": True,
                    "metadata": document_input(normalized, kb_id).metadata,
                }
            result = deeptutor_service.ingest_document(document_input(normalized, kb_id))
            ledger.record(normalized)
            return {**result, "status": "indexed", "deduplicated": False}
        except DeepTutorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc

    return router
