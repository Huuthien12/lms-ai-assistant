"""One verified application flow into Quan's existing learning domains."""
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.routing import APIRoute
from fastapi.exceptions import RequestValidationError
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field, field_validator
from backend.services.ai.quiz_service import QuizService
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.explanation_service import ExplanationService
from backend.services.ai.grading_service import GradingService
from deeptutor_integration.auth_contracts import CourseAction
from deeptutor_integration.document_normalizer import DocumentNormalizer
from deeptutor_integration.errors import DeepTutorError
from quiz_lifecycle import QuizDefinitionRequest, StartAttemptRequest, SubmittedAnswer
from learning_evidence import FlashcardRegistration, FlashcardReviewRequest
from verified_learning_repository import context_payload, restore_context
from verified_chat import verified_chat


class SafeLearningRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try: return await handler(request)
            except HTTPException: raise
            except RequestValidationError:
                raise HTTPException(422,detail={"code":"invalid_request","message":"Learning request is invalid."}) from None
            except DeepTutorError as error: raise HTTPException(error.status_code,detail=error.as_dict()) from None
            except ValueError as error:
                code=str(error).split(":",1)[0]
                known={"artifact_not_found":404,"attempt_not_found":404,"quiz_not_found":404,
                       "already_submitted":409,"invalid_question":422,"invalid_option":422,"course_mismatch":403,
                       "idempotency_conflict":409,"persistence_failure":503,"mastery_not_found":404,
                       "INSUFFICIENT_GROUNDED_CONTEXT":409,"QUIZ_GENERATION_FAILED":502,
                       "FLASHCARD_GENERATION_FAILED":502,"INVALID_QUIZ_SCHEMA":502,"INVALID_FLASHCARD_SCHEMA":502}
                status=known.get(code,503)
                if code not in known: code="learning_dependency_unavailable"
                raise HTTPException(status,detail={"code":code,"message":"Learning request could not be completed."}) from None
            except Exception:
                raise HTTPException(503,detail={"code":"learning_dependency_unavailable","message":"Learning dependency is unavailable."}) from None
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
            **public,"context_id":context.context_id,"sources":context.citations()}


def create_verified_learning_router(authorizer,publications,repository,orchestrator,chat_service,recommendations):
    router=APIRouter(prefix="/learning",tags=["verified-learning"],route_class=SafeLearningRoute)
    quizzes=QuizService(orchestrator); cards=FlashcardService(orchestrator); explanations=ExplanationService(orchestrator)
    grader=GradingService(); normalizer=DocumentNormalizer()

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
        resources=access.moodle_adapter().list_file_resources(scope.moodle_course_id)
        return {"course_id":scope.course_key,"resources":resources,"publications":publications.documents(scope)}

    @router.post("/courses/{course_id}/documents/{resource_id}/sync")
    def sync(course_id:str,resource_id:int,access=Depends(authorizer)):
        scope=access.scope(course_id,action=CourseAction.SYNC_COURSE_RESOURCE)
        source=access.moodle_adapter().get_source_document(scope.moodle_course_id,resource_id)
        return publications.publish(scope,normalizer.normalize(source))

    @router.delete("/courses/{course_id}/documents/{resource_id}")
    def delete_document(course_id:str,resource_id:int,access=Depends(authorizer)):
        scope=access.scope(course_id,action=CourseAction.SYNC_COURSE_RESOURCE)
        return publications.delete(scope,str(resource_id))

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
    async def generate_quiz(course_id:str,request:GenerationInput,access=Depends(authorizer)):
        scope=await run_in_threadpool(access.scope,course_id,request.kb_name)
        async with learning_context(publications,scope,request.question) as context:
            internal=await quizzes.generate_grounded_quiz(topic=request.topic,question_count=request.count,
                difficulty=request.difficulty,question_types=["mcq"],retrieved_context=context.text(),
                source_metadata=context.citations(),client_facing=False)
            questions=[{"question_id":f"q{index}",**q} for index,q in enumerate(internal["questions"],1)]
            definition=QuizDefinitionRequest(quiz_id=uuid4().hex,course_id=scope.course_key,
                topic=request.topic,difficulty=request.difficulty,questions=questions)
            await run_in_threadpool(repository.quizzes.save_quiz,definition)
            await run_in_threadpool(repository.put,"quiz",definition.quiz_id,scope,{"context":context_payload(context)})
            return public_quiz(definition.model_dump(),context)

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
        await owned_attempt(attempt_id,access)
        return await run_in_threadpool(repository.quizzes.submit,attempt_id,[a.model_dump() for a in request.answers],grader)

    @router.get("/attempts/{attempt_id}/review")
    async def review(attempt_id:str,access=Depends(authorizer)):
        attempt,scope,context=await owned_attempt(attempt_id,access)
        if attempt["status"]!="SUBMITTED": raise HTTPException(409,detail={"code":"attempt_not_submitted","message":"Attempt is not submitted."})
        quiz=await run_in_threadpool(repository.quizzes.quiz,attempt["quiz_id"])
        answers=await run_in_threadpool(repository.answers,attempt_id)
        results=[]
        lease=publications.ledger._locked(); await run_in_threadpool(lease.__enter__)
        try:
            try: publications.revalidate(context); active=True
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
            generated=await cards.generate_grounded_flashcards(topic=request.topic,count=request.count,
                difficulty=request.difficulty,retrieved_context=context.text(),source_metadata=context.citations())
            result=[]
            for card in generated["flashcards"]:
                identifier=uuid4().hex
                await run_in_threadpool(repository.evidence.register_flashcard,
                    FlashcardRegistration(flashcard_id=identifier,course_id=scope.course_key,topic=request.topic))
                payload={"card":card,"context":context_payload(context)}
                await run_in_threadpool(repository.put,"flashcard",identifier,scope,payload)
                result.append({"flashcard_id":identifier,**card})
            return {"flashcards":result,"sources":context.citations(),"context_id":context.context_id}

    @router.get("/courses/{course_id}/flashcards")
    def list_cards(course_id:str,access=Depends(authorizer)):
        scope=access.scope(course_id)
        return {"flashcards":[{"flashcard_id":item["artifact_id"],**item["payload"]["card"]}
                              for item in repository.list("flashcard",scope)]}

    @router.post("/flashcards/{flashcard_id}/reviews")
    async def review_card(flashcard_id:str,request:ReviewInput,access=Depends(authorizer)):
        _,scope,_=await owned("flashcard",flashcard_id,access)
        return await run_in_threadpool(repository.evidence.review,flashcard_id,
            FlashcardReviewRequest(student_id=scope.owner_ref,rating=request.rating,review_id=request.review_id))

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
