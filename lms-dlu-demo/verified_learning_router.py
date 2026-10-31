"""One verified application flow into Quan's existing learning domains."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import os
import time
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.services.ai.quiz_service import QuizService, record_generation_stage, record_quiz_stage
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.explanation_service import ExplanationService
from backend.services.ai.grading_service import GradingService
from deeptutor_integration.auth_contracts import CourseAction
from deeptutor_integration.document_normalizer import DocumentNormalizer
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.verified_publication import VerifiedPublicationService
from quiz_lifecycle import StartAttemptRequest, SubmittedAnswer
from learning_evidence import FlashcardReviewRequest
from verified_learning_repository import context_payload, restore_context
from verified_chat import verified_chat
from backend.services.ai.learning_context import LearningScope
from learning_generation import LearningGenerationService
from deeptutor_integration.moodle_publication import MoodlePublicationAdapter
from deeptutor_integration.auth_contracts import AuthContractError


class SafeLearningRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            kind=None
            if request.method == "POST":
                kind=("quiz" if request.url.path.endswith("/quizzes") else
                      "flashcard" if request.url.path.endswith("/flashcards") else None)
            if kind:
                request.state.learning_kind=kind
                request.state.learning_correlation_id=uuid4().hex
                request.state.learning_started_at=time.monotonic()
            try: return await handler(request)
            except HTTPException: raise
            except AuthContractError as error: raise HTTPException(error.status_code,detail=error.public_payload()) from None
            except RequestValidationError:
                raise HTTPException(422,detail={"code":"invalid_request","message":"Learning request is invalid."}) from None
            except DeepTutorError as error: raise HTTPException(error.status_code,detail=error.as_dict()) from None
            except ValueError as error:
                code=str(error).split(":",1)[0]
                diagnostics=getattr(error,"diagnostics",{})
                if code=="INVALID_QUIZ_SCHEMA" and isinstance(diagnostics,dict):
                    reason=diagnostics.get("grounding_failure_reason")
                    if reason=="answer_span_mismatch": code="QUIZ_ANSWER_SPAN_MISMATCH"
                    elif reason: code="QUIZ_GROUNDING_FAILED"
                known={"artifact_not_found":404,"attempt_not_found":404,"quiz_not_found":404,
                       "already_submitted":409,"invalid_question":422,"invalid_option":422,"course_mismatch":403,
                       "idempotency_conflict":409,"learning_scope_forbidden":403,"flashcard_conflict":409,"flashcard_context_unavailable":409,
                       "learning_context_verifier_not_configured":503,"learning_context_rejected":409,"INVALID_LEARNING_CONTEXT":422,"persistence_failure":503,"mastery_not_found":404,
                       "INSUFFICIENT_GROUNDED_CONTEXT":409,"QUIZ_GENERATION_FAILED":502,
                       "FLASHCARD_GENERATION_FAILED":502,"INVALID_QUIZ_SCHEMA":502,"INVALID_FLASHCARD_SCHEMA":502,
                       "QUIZ_GROUNDING_FAILED":422,"QUIZ_ANSWER_SPAN_MISMATCH":422,
                       "LEARNING_GENERATION_TIMEOUT":504,"LEARNING_PROVIDER_UNCONFIGURED":503,
                        "LEARNING_PROVIDER_UNAVAILABLE":503,"LEARNING_PROVIDER_REQUEST_TOO_LARGE":413,
                       "LEARNING_RATE_LIMITED":429,"invalid_chapter":422,"NO_NEW_FLASHCARDS":409}
                known.update({"attempt_not_submitted":409,"trusted_topic_mapping_unavailable":409,
                              "review_batch_lease_lost":409,"review_batch_not_found":404,
                              "invalid_flashcard":422})
                status=known.get(code,503)
                if code not in known: code="learning_dependency_unavailable"
                detail={"code":code,"message":"Learning request could not be completed."}
                if code in {"QUIZ_GROUNDING_FAILED","QUIZ_ANSWER_SPAN_MISMATCH"}:
                    for key in ("requested_count","validated_count"):
                        value=diagnostics.get(key) if isinstance(diagnostics,dict) else None
                        if type(value) is int and value >= 0:
                            detail[key]=value
                raise HTTPException(status,detail=detail) from None
            except Exception:
                raise HTTPException(503,detail={"code":"learning_dependency_unavailable","message":"Learning dependency is unavailable."}) from None
            finally:
                if kind:
                    correlation_id=request.state.learning_correlation_id
                    started=request.state.learning_started_at
                    if not getattr(request.state,"learning_authorization_recorded",False):
                        record_generation_stage(kind,correlation_id,
                            "authorization_pre_generation" if kind=="quiz" else "authorization",
                            "failed",(time.monotonic()-started)*1000)
                    if not getattr(request.state,"learning_response_recorded",False):
                        record_generation_stage(kind,correlation_id,"response","failed",(time.monotonic()-started)*1000)
        return safe


class ChatInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    question: str=Field(min_length=1,max_length=8000)
    kb_name: str | None=None
    @field_validator("question","kb_name")
    @classmethod
    def nonblank(cls,value):
        if value is not None:
            value=value.strip()
            if not value: raise ValueError("Value must not be blank.")
        return value


class GenerationInput(ChatInput):
    topic: str=Field(min_length=1,max_length=256)
    count: int=Field(default=3,ge=1,le=20,strict=True)
    difficulty: Literal["easy","medium","hard","mixed"]="medium"
    scope_mode: Literal["course","chapter"]="course"
    chapter_id: str | None=Field(default=None,min_length=1,max_length=200)
    @field_validator("topic")
    @classmethod
    def topic_nonblank(cls,value):
        value=value.strip()
        if not value: raise ValueError("Topic must not be blank.")
        return value

    @field_validator("chapter_id")
    @classmethod
    def chapter_nonblank(cls,value):
        return value.strip() if value is not None else value

    @property
    def selected_document_id(self):
        if self.scope_mode=="chapter":
            if not self.chapter_id: raise ValueError("invalid_chapter")
            return self.chapter_id
        if self.chapter_id is not None: raise ValueError("invalid_chapter")
        return None


class SubmissionInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    answers: list[SubmittedAnswer]=Field(default_factory=list)


class ReviewInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    rating: Literal["AGAIN","HARD","GOOD","EASY"]
    review_id: str=Field(min_length=1,max_length=64)


@asynccontextmanager
async def learning_context(publications,scope,question,*,deadline=None,document_id=None):
    kwargs={"deadline":deadline}
    if document_id is not None: kwargs["document_id"]=document_id
    lease=publications.context(scope,question,**kwargs)
    context=await run_in_threadpool(lease.__enter__)
    try:
        if not context.chunks: raise DeepTutorError("no_verified_context","No verified active context is available.",status_code=409)
        publications.revalidate(context)
        yield context
    finally: await run_in_threadpool(lease.__exit__,None,None,None)


def public_quiz(quiz,context,display_scope=None):
    public=QuizService.to_public_result({"questions":quiz["questions"]})
    for original,item in zip(quiz["questions"],public["questions"]): item["question_id"]=original["question_id"]
    result={"quiz_id":quiz["quiz_id"],"course_id":quiz["course_id"],"topic":quiz["topic"],
            **public,"context_id":context.context_id,"sources":VerifiedPublicationService.learning_context(context).source_metadata()}
    if isinstance(display_scope,dict) and display_scope.get("scope_mode") in {"chapter","course"}:
        result["scope_mode"]=display_scope["scope_mode"]
        if isinstance(display_scope.get("chapter_id"),str): result["chapter_id"]=display_scope["chapter_id"]
    return result


def question_citations(question,citations):
    """Select only citations whose stable source ID was retained with this question."""
    question_metadata=question.get("source_metadata",[]) if isinstance(question,dict) else []
    if isinstance(question_metadata,dict): question_metadata=[question_metadata]
    source_ids={source.get("source_id") for source in question_metadata
                if isinstance(source,dict) and isinstance(source.get("source_id"),str)}
    return [source for source in citations
            if isinstance(source,dict) and source.get("source_id") in source_ids]


@asynccontextmanager
async def trusted_question_context(publications,access,scope,question):
    """Issue a fresh receipt only for one unambiguous persisted provenance binding."""
    provenance=question.get("trusted_provenance") if isinstance(question,dict) else None
    bindings=provenance.get("bindings") if isinstance(provenance,dict) and provenance.get("version")==1 else None
    if not isinstance(bindings,list) or not bindings:
        raise ValueError("trusted_topic_mapping_unavailable")
    required={(item.get("source_id"),item.get("chapter_id"),item.get("version"),item.get("content_hash"))
              for item in bindings if isinstance(item,dict)}
    if len(required)!=len(bindings) or any(not all(item) for item in required):
        raise ValueError("trusted_topic_mapping_unavailable")
    chapters={item[1] for item in required}
    if len(chapters)!=1:
        raise ValueError("trusted_topic_mapping_unavailable")
    await run_in_threadpool(access.reauthorize,scope)
    async with learning_context(publications,scope,next(iter(chapters)),document_id=next(iter(chapters))) as context:
        actual={(source.source_id,source.document_id,source.version,source.content_hash)
                for source in publications.learning_context(context).sources}
        if not required <= actual:
            raise ValueError("trusted_topic_mapping_unavailable")
        yield context


def create_verified_learning_router(authorizer,publications,repository,orchestrator,chat_service,recommendations,
                                    *,request_timeout_seconds=None,retrieval_timeout_seconds=None,
                                    persistence_reserve_seconds=None):
    router=APIRouter(prefix="/learning",tags=["verified-learning"],route_class=SafeLearningRoute)
    quizzes=QuizService(orchestrator); cards=FlashcardService(orchestrator); explanations=ExplanationService(orchestrator)
    grader=GradingService(); moodle=MoodlePublicationAdapter(publications)
    request_timeout=float(request_timeout_seconds or os.getenv("LEARNING_REQUEST_TIMEOUT_SECONDS","150"))
    retrieval_timeout=float(retrieval_timeout_seconds or os.getenv("LEARNING_RETRIEVAL_TIMEOUT_SECONDS","60"))
    persistence_reserve=float(persistence_reserve_seconds or os.getenv("LEARNING_PERSISTENCE_RESERVE_SECONDS","20"))
    if min(request_timeout,retrieval_timeout,persistence_reserve)<=0 or retrieval_timeout+persistence_reserve>=request_timeout:
        raise ValueError("Invalid learning timeout configuration")

    async def generate_with_authority(access,context,kind,request,correlation_id,deadline,timeout_seconds,
                                      existing_pairs=None):
        failures=[]
        def validate(scope,learning):
            try: return publications.validate_learning_context(scope,learning,access)
            except Exception as error:
                failures.append(error); raise
        generation=LearningGenerationService(quizzes,cards,repository.quizzes,repository.evidence,context_validator=validate)
        learning=publications.learning_context(context)
        try:
            if kind=="quiz":
                return await generation.generate_quiz(learning.scope,learning,topic=request.topic,
                    question_count=request.count,difficulty=request.difficulty,correlation_id=correlation_id,
                    deadline=deadline,timeout_seconds=timeout_seconds)
            return await generation.generate_flashcards(learning.scope,learning,topic=request.topic,
                count=request.count,difficulty=request.difficulty,correlation_id=correlation_id,
                deadline=deadline,timeout_seconds=timeout_seconds,existing_pairs=existing_pairs)
        except ValueError:
            if failures: raise failures[-1]
            raise

    def learning_scope(scope): return LearningScope(owner_id=scope.owner_ref,course_id=scope.course_key)

    def saved_flashcard_pairs(scope):
        # shortcut: concurrent generation can race without a normalized DB key, add one in a future additive migration.
        pairs=set()
        for item in repository.list("flashcard",scope):
            card=repository.evidence.flashcard(item["artifact_id"],learning_scope(scope))
            pairs.add((" ".join(card["front_text"].casefold().split()),
                       " ".join(card["back_text"].casefold().split())))
        return pairs

    async def owned(kind,identifier,access):
        artifact=await run_in_threadpool(repository.get,kind,identifier)
        access.require_owner(artifact["owner_ref"])
        scope=await run_in_threadpool(access.scope,artifact["course_id"])
        context=restore_context(artifact["payload"]["context"])
        if context.scope!=scope: raise HTTPException(403,detail={"code":"context_scope_denied","message":"Context scope is not permitted."})
        return artifact,scope,context

    async def owned_attempt(identifier,access):
        attempt=await run_in_threadpool(repository.attempt,identifier)
        access.require_owner(attempt["owner_ref"])
        await run_in_threadpool(access.scope,attempt["course_id"])
        artifact,scope,context=await owned("quiz",attempt["quiz_id"],access)
        return attempt,scope,context

    @router.on_event("startup")
    def initialize(): repository.ensure_schema()

    @router.get("/courses/{course_id}/documents")
    def documents(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        published=publications.documents(scope)
        return {"course_id":scope.course_key,"resources":[],"publications":published}

    @router.get("/courses/{course_id}/resources")
    def resources(course_id:str,access=Depends(authorizer)):
        return {"resources":moodle.resources(access,course_id)}

    @router.post("/courses/{course_id}/sync")
    def sync_course(course_id:str,access=Depends(authorizer)): return moodle.sync(access,course_id)

    @router.post("/courses/{course_id}/documents/{resource_id}/sync")
    def sync(course_id:str,resource_id:str,access=Depends(authorizer)):
        return moodle.sync_document(access,course_id,resource_id)

    @router.delete("/courses/{course_id}/documents/{resource_id}")
    def delete_document(course_id:str,resource_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id,action=CourseAction.SYNC_COURSE_RESOURCE)
        return publications.delete(scope,resource_id)

    @router.post("/courses/{course_id}/chat")
    async def chat(course_id:str,request:ChatInput,access=Depends(authorizer)):
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        response=await verified_chat(publications,access,request.question,scope.course_key,scope.kb_name,chat_service)
        await run_in_threadpool(repository.put,"chat",uuid4().hex,scope,{"question":request.question,"response":response})
        return response

    @router.get("/courses/{course_id}/history")
    def history(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        return {"history":[item["payload"] for item in repository.list("chat",scope)]}

    @router.delete("/courses/{course_id}/history")
    def clear_history(course_id:str,access=Depends(authorizer)):
        repository.clear_history(access.scope(course_id)); return {"status":"cleared"}

    @router.post("/courses/{course_id}/quizzes")
    async def generate_quiz(course_id:str,request:GenerationInput,http_request:Request,access=Depends(authorizer)):
        correlation_id=getattr(http_request.state,"learning_correlation_id",uuid4().hex)
        request_started=getattr(http_request.state,"learning_started_at",time.monotonic())
        deadline=request_started+request_timeout
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        record_quiz_stage(correlation_id,"authorization_pre_generation","passed",(time.monotonic()-request_started)*1000)
        http_request.state.learning_authorization_recorded=True
        retrieval_started=time.monotonic(); retrieval_finished=False
        try:
            async with learning_context(publications,scope,request.question,
                                        document_id=request.selected_document_id,
                                        deadline=min(deadline-persistence_reserve,retrieval_started+retrieval_timeout)) as context:
                record_quiz_stage(correlation_id,"retrieval_context","passed",(time.monotonic()-retrieval_started)*1000)
                retrieval_finished=True
                provider_timeout=deadline-time.monotonic()-persistence_reserve
                if provider_timeout<=0: raise ValueError("LEARNING_GENERATION_TIMEOUT")
                generated=await generate_with_authority(access,context,"quiz",request,correlation_id,deadline,provider_timeout)
                artifact_started=time.monotonic()
                record_quiz_stage(correlation_id,"artifact_persistence","started",0)
                try:
                    await run_in_threadpool(repository.put,"quiz",generated["quiz_id"],scope,{
                        "context":context_payload(context),
                        "quiz_display":{"scope_mode":request.scope_mode,"chapter_id":request.selected_document_id},
                    })
                except Exception:
                    record_quiz_stage(correlation_id,"artifact_persistence","failed",(time.monotonic()-artifact_started)*1000)
                    raise
                record_quiz_stage(correlation_id,"artifact_persistence","passed",(time.monotonic()-artifact_started)*1000)
                # Public projection comes from Quan, with stable IDs and no raw context.
                result={**generated,"topic":request.topic,"context_id":context.context_id,
                        "scope_mode":request.scope_mode,
                        "sources":publications.learning_context(context).source_metadata()}
                if request.selected_document_id is not None: result["chapter_id"]=request.selected_document_id
                record_quiz_stage(correlation_id,"response","passed",(time.monotonic()-request_started)*1000)
                http_request.state.learning_response_recorded=True
                return result
        except Exception:
            if not retrieval_finished:
                record_quiz_stage(correlation_id,"retrieval_context","failed",(time.monotonic()-retrieval_started)*1000)
            raise

    @router.get("/quizzes/{quiz_id}")
    async def quiz(quiz_id:str,access=Depends(authorizer)):
        artifact,_,context=await owned("quiz",quiz_id,access)
        quiz=await run_in_threadpool(repository.quizzes.quiz,quiz_id)
        return public_quiz(quiz,context,artifact["payload"].get("quiz_display"))

    @router.post("/quizzes/{quiz_id}/attempts")
    async def start(quiz_id:str,access=Depends(authorizer)):
        _,scope,_=await owned("quiz",quiz_id,access)
        return await run_in_threadpool(repository.quizzes.start,
            StartAttemptRequest(student_id=scope.owner_ref,course_id=scope.course_key,quiz_id=quiz_id))

    @router.post("/attempts/{attempt_id}/submit")
    async def submit(attempt_id:str,request:SubmissionInput,access=Depends(authorizer)):
        _,scope,_=await owned_attempt(attempt_id,access)
        return await run_in_threadpool(repository.quizzes.submit,attempt_id,[a.model_dump() for a in request.answers],grader,scope=learning_scope(scope))

    @router.get("/attempts/{attempt_id}/review")
    async def review(attempt_id:str,question_id:list[str] | None=Query(default=None),access=Depends(authorizer)):
        attempt,scope,context=await owned_attempt(attempt_id,access)
        if attempt["status"]!="SUBMITTED": raise HTTPException(409,detail={"code":"attempt_not_submitted","message":"Attempt is not submitted."})
        quiz=await run_in_threadpool(repository.quizzes.quiz,attempt["quiz_id"])
        answers=await run_in_threadpool(repository.answers,attempt_id)
        if question_id is not None:
            requested=set(question_id)
            answers=[answer for answer in answers if answer["question_id"] in requested]
        results=[]
        lease=publications.ledger._locked(); await run_in_threadpool(lease.__enter__)
        try:
            try:
                await run_in_threadpool(access.reauthorize,scope)
                publications.revalidate(context); active=True
            except DeepTutorError: active=False
            for answer in answers:
                item={**answer,"explanation_status":"publication_unavailable" if not active else "provider_unavailable"}
                if active:
                    question=next((q for q in quiz["questions"] if q["question_id"]==answer["question_id"]),None)
                    if question is None:
                        item["explanation_status"]="question_unavailable"
                        results.append(item)
                        continue
                    options={o["id"]:o["text"] for o in question["options"]}
                    item["correct_option_id"]=question["correct_option_id"]
                    item["correct_answer"]=options[question["correct_option_id"]]
                    question_sources=question_citations(question,context.citations())
                    try:
                        explanation=await explanations.generate_explanation(question["question"],
                            options.get(answer["selected_option_id"]),options[question["correct_option_id"]],
                            answer_state=("unanswered" if answer["selected_option_id"] is None
                                          else "correct" if answer.get("correct") else "incorrect"),
                            context=context.text(),source_metadata=question_sources)
                        item.update(explanation_status="available",explanation=explanation["explanation"],
                                    key_concept=explanation["key_concept"],sources=explanation["sources"])
                    except ValueError as error:
                        code=str(error).split(":",1)[0]
                        item["explanation_status"]={
                            "LEARNING_RATE_LIMITED":"provider_rate_limited",
                            "LEARNING_PROVIDER_UNAVAILABLE":"provider_unavailable",
                            "LEARNING_GENERATION_TIMEOUT":"provider_timeout",
                        }.get(code,"provider_unavailable")
                results.append(item)
        finally: await run_in_threadpool(lease.__exit__,None,None,None)
        return {"attempt_id":attempt_id,"results":results}

    @router.post("/attempts/{attempt_id}/review-flashcards")
    async def review_flashcards(attempt_id:str,http_request:Request,access=Depends(authorizer)):
        attempt,scope,_=await owned_attempt(attempt_id,access)
        if attempt["status"]!="SUBMITTED":
            raise HTTPException(409,detail={"code":"attempt_not_submitted","message":"Attempt is not submitted."})
        answers=await run_in_threadpool(repository.answers,attempt_id)
        wrong={item["question_id"] for item in answers if not item["correct"]}
        if not wrong:
            return {"attempt_id":attempt_id,"status":"NO_REVIEW_NEEDED","flashcards":[]}
        quiz=await run_in_threadpool(repository.quizzes.quiz,attempt["quiz_id"])
        questions={item["question_id"]:item for item in quiz["questions"]}
        grouped={}
        for question_id in wrong:
            question=questions.get(question_id); provenance=question.get("trusted_provenance") if question else None
            bindings=provenance.get("bindings") if isinstance(provenance,dict) and provenance.get("version")==1 else None
            chapters={item.get("chapter_id") for item in bindings or [] if isinstance(item,dict) and item.get("chapter_id")}
            if not question or len(chapters)!=1:
                raise HTTPException(409,detail={"code":"trusted_topic_mapping_unavailable","message":"Review material is unavailable."})
            grouped.setdefault(next(iter(chapters)),[]).append(question)
        reservation=await run_in_threadpool(repository.reserve_review_batch,attempt_id,scope,{"chapters":sorted(grouped)})
        if reservation["status"]=="READY":
            return {"attempt_id":attempt_id,"batch_id":reservation["batch_id"],"status":"READY","flashcards":[]}
        if reservation["status"]=="PENDING" and not reservation.get("lease_id"):
            return {"attempt_id":attempt_id,"batch_id":reservation["batch_id"],"status":"PENDING","flashcards":[]}
        batch_cards=[]; chapters={}; payloads={}
        existing_pairs=await run_in_threadpool(saved_flashcard_pairs,scope)
        generation=LearningGenerationService(quizzes,cards,repository.quizzes,repository.evidence,
            context_validator=lambda scoped,learning: publications.validate_learning_context(scoped,learning,access))
        try:
            for chapter,items in grouped.items():
                async with trusted_question_context(publications,access,scope,items[0]) as context:
                    learning=VerifiedPublicationService.learning_context(context)
                    prepared=await generation.prepare_flashcards(learning.scope,learning,topic=chapter,count=5,difficulty="medium",
                        existing_pairs=existing_pairs,
                        correlation_id=getattr(http_request.state,"learning_correlation_id",uuid4().hex))
                    for card in prepared["_cards"]:
                        existing_pairs.add((" ".join(card.front_text.casefold().split()),
                                            " ".join(card.back_text.casefold().split())))
                        batch_cards.append(card); chapters[card.flashcard_id]=chapter; payloads[card.flashcard_id]={"context":context_payload(context)}
            result=await run_in_threadpool(repository.publish_review_batch,reservation["batch_id"],reservation["lease_id"],scope,batch_cards,chapters,payloads)
        except Exception:
            await run_in_threadpool(repository.fail_review_batch,reservation["batch_id"],reservation["lease_id"],scope)
            raise
        return {"attempt_id":attempt_id,"batch_id":result["batch_id"],"status":result["status"],"flashcards":[
            {"flashcard_id":card.flashcard_id,"front_text":card.front_text,"back_text":card.back_text,"topic":card.topic} for card in batch_cards]}

    @router.post("/courses/{course_id}/flashcards")
    async def generate_cards(course_id:str,request:GenerationInput,http_request:Request,access=Depends(authorizer)):
        correlation_id=getattr(http_request.state,"learning_correlation_id",uuid4().hex)
        request_started=getattr(http_request.state,"learning_started_at",time.monotonic())
        deadline=request_started+request_timeout
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        record_generation_stage("flashcard",correlation_id,"authorization","passed",(time.monotonic()-request_started)*1000)
        http_request.state.learning_authorization_recorded=True
        retrieval_started=time.monotonic(); retrieval_finished=False
        try:
            async with learning_context(publications,scope,request.question,
                                        document_id=request.selected_document_id,
                                        deadline=min(deadline-persistence_reserve,retrieval_started+retrieval_timeout)) as context:
                record_generation_stage("flashcard",correlation_id,"retrieval","passed",(time.monotonic()-retrieval_started)*1000)
                retrieval_finished=True
                provider_timeout=deadline-time.monotonic()-persistence_reserve
                if provider_timeout<=0: raise ValueError("LEARNING_GENERATION_TIMEOUT")
                existing_pairs=await run_in_threadpool(saved_flashcard_pairs,scope)
                generated=await generate_with_authority(access,context,"flashcard",request,correlation_id,
                    deadline,provider_timeout,existing_pairs)
                artifact_started=time.monotonic()
                record_generation_stage("flashcard",correlation_id,"artifact_persistence","started",0)
                try:
                    await run_in_threadpool(repository.put_many,"flashcard",
                        [(card["flashcard_id"],{"context":context_payload(context)}) for card in generated["flashcards"]],scope)
                except Exception:
                    record_generation_stage("flashcard",correlation_id,"artifact_persistence","failed",(time.monotonic()-artifact_started)*1000)
                    raise
                record_generation_stage("flashcard",correlation_id,"artifact_persistence","passed",(time.monotonic()-artifact_started)*1000)
                result={**generated,"sources":context.citations(),"context_id":context.context_id}
                record_generation_stage("flashcard",correlation_id,"response","passed",(time.monotonic()-request_started)*1000)
                http_request.state.learning_response_recorded=True
                return result
        except Exception:
            if not retrieval_finished:
                record_generation_stage("flashcard",correlation_id,"retrieval","failed",(time.monotonic()-retrieval_started)*1000)
            raise

    @router.get("/courses/{course_id}/flashcards")
    def list_cards(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        result=[]
        for item in repository.list("flashcard",scope):
            card=repository.evidence.flashcard(item["artifact_id"],learning_scope(scope))
            result.append({key:card[key] for key in ("flashcard_id","front_text","back_text","topic")})
            result[-1]["sources"]=card["learning_context"]["sources"] if card.get("learning_context") else []
            result[-1].update(repository.evidence.latest_review(item["artifact_id"],learning_scope(scope)))
        return {"flashcards":result}

    @router.post("/flashcards/{flashcard_id}/reviews")
    async def review_card(flashcard_id:str,request:ReviewInput,access=Depends(authorizer)):
        _,scope,_=await owned("flashcard",flashcard_id,access)
        return await run_in_threadpool(repository.evidence.review,flashcard_id,
            FlashcardReviewRequest(student_id=scope.owner_ref,rating=request.rating,review_id=request.review_id),scope=learning_scope(scope))

    @router.get("/courses/{course_id}/progress")
    def progress(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        try: topics=repository.evidence.mastery_for(scope.owner_ref,scope.course_key)
        except ValueError as error:
            if str(error)!="mastery_not_found": raise
            topics=[]
        # Rule recommendations use server evidence only; no extra generation or ML claim.
        return {"owner_ref":scope.owner_ref,"course_id":scope.course_key,"topics":topics,
                "recommendations":[recommendations._evaluate_rule_first(topic) for topic in topics],
                "mastery_model":"heuristic/rule-based"}

    return router
