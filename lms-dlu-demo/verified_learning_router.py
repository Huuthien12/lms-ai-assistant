"""One verified application flow into Quan's existing learning domains."""
from contextlib import asynccontextmanager
from dataclasses import asdict
import time
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.services.ai.quiz_service import QuizService, record_quiz_stage
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
            if request.method == "POST" and request.url.path.endswith("/quizzes"):
                request.state.quiz_correlation_id = uuid4().hex
                request.state.quiz_started_at = time.monotonic()
            try: return await handler(request)
            except HTTPException: raise
            except AuthContractError as error: raise HTTPException(error.status_code,detail=error.public_payload()) from None
            except RequestValidationError:
                raise HTTPException(422,detail={"code":"invalid_request","message":"Learning request is invalid."}) from None
            except DeepTutorError as error: raise HTTPException(error.status_code,detail=error.as_dict()) from None
            except ValueError as error:
                code=str(error).split(":",1)[0]
                known={"artifact_not_found":404,"attempt_not_found":404,"quiz_not_found":404,
                       "already_submitted":409,"invalid_question":422,"invalid_option":422,"course_mismatch":403,
                       "idempotency_conflict":409,"learning_scope_forbidden":403,"flashcard_conflict":409,"flashcard_context_unavailable":409,
                       "learning_context_verifier_not_configured":503,"learning_context_rejected":409,"INVALID_LEARNING_CONTEXT":422,"persistence_failure":503,"mastery_not_found":404,
                       "INSUFFICIENT_GROUNDED_CONTEXT":409,"QUIZ_GENERATION_FAILED":502,
                       "FLASHCARD_GENERATION_FAILED":502,"INVALID_QUIZ_SCHEMA":502,"INVALID_FLASHCARD_SCHEMA":502}
                status=known.get(code,503)
                if code not in known: code="learning_dependency_unavailable"
                raise HTTPException(status,detail={"code":code,"message":"Learning request could not be completed."}) from None
            except Exception:
                raise HTTPException(503,detail={"code":"learning_dependency_unavailable","message":"Learning dependency is unavailable."}) from None
            finally:
                if hasattr(request.state,"quiz_started_at") and not getattr(request.state,"quiz_authorization_recorded",False):
                    record_quiz_stage(request.state.quiz_correlation_id,"authorization_pre_generation","failed",(time.monotonic()-request.state.quiz_started_at)*1000)
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
    @field_validator("topic")
    @classmethod
    def topic_nonblank(cls,value):
        value=value.strip()
        if not value: raise ValueError("Topic must not be blank.")
        return value


class SubmissionInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    answers: list[SubmittedAnswer]=Field(default_factory=list)


class ReviewInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    rating: Literal["AGAIN","HARD","GOOD","EASY"]
    review_id: str=Field(min_length=1,max_length=64)


@asynccontextmanager
async def learning_context(publications,scope,question):
    lease=publications.context(scope,question)
    context=await run_in_threadpool(lease.__enter__)
    try:
        if not context.chunks: raise DeepTutorError("no_verified_context","No verified active context is available.",status_code=409)
        publications.revalidate(context)
        yield context
    finally: await run_in_threadpool(lease.__exit__,None,None,None)


def public_quiz(quiz,context):
    public=QuizService.to_public_result({"questions":quiz["questions"]})
    for original,item in zip(quiz["questions"],public["questions"]): item["question_id"]=original["question_id"]
    return {"quiz_id":quiz["quiz_id"],"course_id":quiz["course_id"],"topic":quiz["topic"],
            **public,"context_id":context.context_id,"sources":VerifiedPublicationService.learning_context(context).source_metadata()}


def create_verified_learning_router(authorizer,publications,repository,orchestrator,chat_service,recommendations):
    router=APIRouter(prefix="/learning",tags=["verified-learning"],route_class=SafeLearningRoute)
    quizzes=QuizService(orchestrator); cards=FlashcardService(orchestrator); explanations=ExplanationService(orchestrator)
    grader=GradingService(); moodle=MoodlePublicationAdapter(publications)

    async def generate_with_authority(access,context,kind,request,correlation_id=None):
        failures=[]
        def validate(scope,learning):
            try: return publications.validate_learning_context(scope,learning,access)
            except Exception as error:
                failures.append(error); raise
        generation=LearningGenerationService(quizzes,cards,repository.quizzes,repository.evidence,context_validator=validate)
        learning=publications.learning_context(context)
        try:
            if kind=="quiz":
                return await generation.generate_quiz(learning.scope,learning,topic=request.topic,question_count=request.count,difficulty=request.difficulty,correlation_id=correlation_id)
            return await generation.generate_flashcards(learning.scope,learning,topic=request.topic,count=request.count,difficulty=request.difficulty)
        except ValueError:
            if failures: raise failures[-1]
            raise

    def learning_scope(scope): return LearningScope(owner_id=scope.owner_ref,course_id=scope.course_key)

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
        correlation_id=getattr(http_request.state,"quiz_correlation_id",uuid4().hex)
        request_started=getattr(http_request.state,"quiz_started_at",time.monotonic())
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        record_quiz_stage(correlation_id,"authorization_pre_generation","passed",(time.monotonic()-request_started)*1000)
        http_request.state.quiz_authorization_recorded=True
        retrieval_started=time.monotonic(); retrieval_finished=False
        try:
            async with learning_context(publications,scope,request.question) as context:
                record_quiz_stage(correlation_id,"retrieval_context","passed",(time.monotonic()-retrieval_started)*1000)
                retrieval_finished=True
                generated=await generate_with_authority(access,context,"quiz",request,correlation_id)
                artifact_started=time.monotonic()
                record_quiz_stage(correlation_id,"artifact_persistence","started",0)
                try:
                    await run_in_threadpool(repository.put,"quiz",generated["quiz_id"],scope,{"context":context_payload(context)})
                except Exception:
                    record_quiz_stage(correlation_id,"artifact_persistence","failed",(time.monotonic()-artifact_started)*1000)
                    raise
                record_quiz_stage(correlation_id,"artifact_persistence","passed",(time.monotonic()-artifact_started)*1000)
                # Public projection comes from Quan, with stable IDs and no raw context.
                return {**generated,"topic":request.topic,"context_id":context.context_id,"sources":publications.learning_context(context).source_metadata()}
        except Exception:
            if not retrieval_finished:
                record_quiz_stage(correlation_id,"retrieval_context","failed",(time.monotonic()-retrieval_started)*1000)
            raise

    @router.get("/quizzes/{quiz_id}")
    async def quiz(quiz_id:str,access=Depends(authorizer)):
        _,_,context=await owned("quiz",quiz_id,access)
        quiz=await run_in_threadpool(repository.quizzes.quiz,quiz_id)
        return public_quiz(quiz,context)

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
    async def review(attempt_id:str,access=Depends(authorizer)):
        attempt,scope,context=await owned_attempt(attempt_id,access)
        if attempt["status"]!="SUBMITTED": raise HTTPException(409,detail={"code":"attempt_not_submitted","message":"Attempt is not submitted."})
        quiz=await run_in_threadpool(repository.quizzes.quiz,attempt["quiz_id"])
        answers=await run_in_threadpool(repository.answers,attempt_id)
        results=[]
        lease=publications.ledger._locked(); await run_in_threadpool(lease.__enter__)
        try:
            try:
                await run_in_threadpool(access.reauthorize,scope)
                publications.revalidate(context); active=True
            except DeepTutorError: active=False
            for answer in answers:
                item={**answer,"explanation_status":"unavailable"}
                if active:
                    question=next(q for q in quiz["questions"] if q["question_id"]==answer["question_id"])
                    options={o["id"]:o["text"] for o in question["options"]}
                    try:
                        explanation=await explanations.generate_explanation(question["question"],
                            options.get(answer["selected_option_id"]),options[question["correct_option_id"]],
                            context=context.text(),source_metadata=context.citations())
                        item.update(explanation_status="available",explanation=explanation["explanation"],
                                    key_concept=explanation["key_concept"],sources=explanation["sources"])
                    except ValueError: pass
                results.append(item)
        finally: await run_in_threadpool(lease.__exit__,None,None,None)
        return {"attempt_id":attempt_id,"results":results}

    @router.post("/courses/{course_id}/flashcards")
    async def generate_cards(course_id:str,request:GenerationInput,access=Depends(authorizer)):
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        async with learning_context(publications,scope,request.question) as context:
            generated=await generate_with_authority(access,context,"flashcard",request)
            for card in generated["flashcards"]:
                await run_in_threadpool(repository.put,"flashcard",card["flashcard_id"],scope,{"context":context_payload(context)})
            return {**generated,"sources":context.citations(),"context_id":context.context_id}

    @router.get("/courses/{course_id}/flashcards")
    def list_cards(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        result=[]
        for item in repository.list("flashcard",scope):
            card=repository.evidence.flashcard(item["artifact_id"],learning_scope(scope))
            result.append({key:card[key] for key in ("flashcard_id","front_text","back_text","topic")})
            result[-1]["sources"]=card["learning_context"]["sources"] if card.get("learning_context") else []
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
