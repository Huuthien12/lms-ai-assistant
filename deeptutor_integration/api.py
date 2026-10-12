from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query

from .contracts import DocumentInput, IntegrationResponse, KnowledgeBaseInput, QueryInput
from .errors import DeepTutorError
from .service import DeepTutorService


QueryAccessChecker = Callable[[QueryInput], None]

def _write_auth_not_configured() -> None:
    raise HTTPException(
        status_code=503,
        detail={"code": "deeptutor_write_auth_not_configured", "message": "DeepTutor write authorization is not configured."},
    )


def _query_auth_not_configured() -> QueryAccessChecker:
    raise HTTPException(
        status_code=503,
        detail={"code": "deeptutor_query_auth_not_configured", "message": "DeepTutor query authorization is not configured."},
    )


def create_router(
    service: DeepTutorService,
    write_authorizer: Callable[..., None] | None = None,
    query_authorizer: Callable[..., QueryAccessChecker] | None = None,
    publication_service=None,
) -> APIRouter:
    router = APIRouter(prefix="/deeptutor", tags=["DeepTutor integration"])
    write_dependency = Depends(write_authorizer or _write_auth_not_configured)
    query_dependency = Depends(query_authorizer or _query_auth_not_configured)

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

    @router.post("/documents", response_model=IntegrationResponse, dependencies=[write_dependency])
    def ingest_document(request: DocumentInput):
        return call(lambda: service.ingest_document(request))

    @router.post("/knowledge-bases", response_model=IntegrationResponse, dependencies=[write_dependency])
    def create_knowledge_base(request: KnowledgeBaseInput):
        return call(lambda: service.create_knowledge_base(request))

    @router.post("/query", response_model=IntegrationResponse)
    def query_knowledge_base(request: QueryInput, authorize_query=query_dependency):
        if not callable(authorize_query):
            _query_auth_not_configured()
        authorize_query(request)
        if publication_service is not None:
            def verified_query():
                scope=authorize_query.scope(request.course_id,request.kb_id)
                with publication_service.context(scope,request.question) as context:
                    authorize_query.reauthorize(scope)
                    publication_service.revalidate(context)
                    return {"course_id":scope.course_key,"kb_id":scope.kb_name,"context_id":context.context_id,
                            "result":{"sources":[{**c.citation(),"content":c.content} for c in context.chunks]}}
            return call(verified_query)
        return call(lambda: service.query(request))

    return router
