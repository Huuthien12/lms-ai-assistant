"""Verified application context into Quan's existing chat service."""
from dataclasses import asdict
import json
import logging
import time
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from backend.services.ai.grounded_chat import GroundedChatRequest, GroundedChatResponse, RetrievedContextItem
from deeptutor_integration.errors import DeepTutorError

logger = logging.getLogger(__name__)


async def verified_chat(publications, access, question, course_id, kb_name, chat):
    started=time.monotonic()
    if not callable(getattr(access,"scope",None)):
        raise HTTPException(503,detail={"code":"authorization_not_configured","message":"Authorization is not configured."})
    scope=await run_in_threadpool(access.scope,course_id,kb_name)
    lease=publications.context(scope,question)
    try:
        context=await run_in_threadpool(lease.__enter__)
    except DeepTutorError as error:
        raise HTTPException(error.status_code,detail=error.as_dict()) from None
    retrieval_ms=(time.monotonic()-started)*1000
    try:
        await run_in_threadpool(access.reauthorize,scope)
        publications.revalidate(context)
        response=await chat.chat(GroundedChatRequest(query=question,course_id=scope.course_key,kb_name=scope.kb_name,
            contexts=[RetrievedContextItem(text=c.content,source_id=c.source_ref,title=c.filename,score=c.score,
                        metadata={"page":c.page,"chunk_id":c.chunk_id,
                                  "document_version_id":c.document_version_id}) for c in context.chunks]))
        if (not isinstance(response,GroundedChatResponse) or response.status not in ("success","error")
            or not isinstance(response.answer,str) or response.course_id!=scope.course_key or response.kb_name!=scope.kb_name
            or not isinstance(response.ai,dict) or not isinstance(response.ai.get("provider"),str)
            or not isinstance(response.ai.get("model"),str) or type(response.ai.get("fallback_used")) is not bool):
            raise ValueError("invalid chat response")
        if response.status!="success": raise DeepTutorError("ai_provider_failure","AI provider could not generate a response.",status_code=502)
        await run_in_threadpool(access.reauthorize,scope)
        payload=asdict(response)
        # Use application-owned provenance only, in the same order as prompt sources.
        citations={c.source_ref:c.citation() for c in context.chunks}
        payload["sources"]=[citations[s["source_id"]] for s in response.sources]
        payload["context_id"]=context.context_id
        json.dumps(payload,allow_nan=False)
        logger.info("verified_chat_timing course=%s retrieval_ms=%.1f total_ms=%.1f provider=%s fallback=%s",
                    scope.course_key, retrieval_ms, (time.monotonic()-started)*1000,
                    response.ai["provider"], response.ai["fallback_used"])
        return payload
    except DeepTutorError as error:
        raise HTTPException(error.status_code,detail=error.as_dict()) from None
    except HTTPException: raise
    except Exception:
        raise HTTPException(502,detail={"code":"ai_provider_failure","message":"AI provider could not generate a response."}) from None
    finally:
        await run_in_threadpool(lease.__exit__,None,None,None)
