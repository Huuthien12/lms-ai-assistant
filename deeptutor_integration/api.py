from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from .contracts import DocumentInput, IntegrationResponse, KnowledgeBaseInput, QueryInput
from .errors import DeepTutorError
from .service import DeepTutorService


def create_router(service: DeepTutorService) -> APIRouter:
    router = APIRouter(prefix="/deeptutor", tags=["DeepTutor integration"])

    def call(operation):
        try:
            return IntegrationResponse(success=True, data=operation())
        except DeepTutorError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.as_dict()) from exc

    @router.get("/health", response_model=IntegrationResponse)
    def health():
        return call(service.health)

    @router.get("/status", response_model=IntegrationResponse)
    def status(kb_id: str | None = Query(default=None)):
        return call(lambda: service.status(kb_id))

    @router.post("/documents", response_model=IntegrationResponse)
    def ingest_document(request: DocumentInput):
        return call(lambda: service.ingest_document(request))

    @router.post("/knowledge-bases", response_model=IntegrationResponse)
    def create_knowledge_base(request: KnowledgeBaseInput):
        return call(lambda: service.create_knowledge_base(request))

    @router.post("/query", response_model=IntegrationResponse)
    def query_knowledge_base(request: QueryInput):
        return call(lambda: service.query(request))

    return router
