"""Generation/persistence adapter for Thiện's verified retrieval caller.

Never expose VerifiedLearningContext as a client request model. Call only after
the shared guard and verified retrieval have succeeded. No arbitrary KB search
or provider payload is exposed to the integration caller.
"""
import uuid
import time
import asyncio

from backend.services.ai.learning_context import LearningScope, VerifiedLearningContext
from backend.services.ai.quiz_service import record_generation_stage, record_quiz_stage, schema_log_fields
from backend.services.ai.quiz_service import QuizService
from quiz_lifecycle import QuizDefinitionRequest
from learning_evidence import FlashcardRegistration


class LearningGenerationService:
    def __init__(self, quiz_service, flashcard_service, quizzes, evidence, *, context_validator=None):
        self.quiz_service, self.flashcard_service = quiz_service, flashcard_service
        self.quizzes, self.evidence = quizzes, evidence
        self.context_validator = context_validator

    async def _context(self, scope: LearningScope, context: VerifiedLearningContext):
        if not isinstance(scope, LearningScope) or not isinstance(context, VerifiedLearningContext):
            raise ValueError("INVALID_LEARNING_CONTEXT")
        scope.require(context.scope.owner_id, context.scope.course_id)
        if not context.sources:
            raise ValueError("INSUFFICIENT_GROUNDED_CONTEXT")
        # Shape/type/flags cannot establish trust. The shared integration layer
        # must revalidate its receipt, active sources and current authorization.
        if self.context_validator is None:
            raise ValueError("learning_context_verifier_not_configured")
        try:
            accepted = await asyncio.to_thread(self.context_validator,scope,context)
        except Exception:
            raise ValueError("learning_context_rejected") from None
        if accepted is not True:
            raise ValueError("learning_context_rejected")

    @staticmethod
    def _may_schema_retry(kind, error, remaining):
        expected="INVALID_QUIZ_SCHEMA" if kind=="quiz" else "INVALID_FLASHCARD_SCHEMA"
        diagnostics=getattr(error,"diagnostics",{})
        return (str(error).split(":",1)[0] == expected and remaining > 0
                and not diagnostics.get("grounding_failure_reason"))

    async def _generate_with_schema_retry(self, kind, generate, correlation_id,
                                          timeout_seconds, kwargs):
        started=time.monotonic()
        try:
            return await generate(**kwargs)
        except ValueError as error:
            code=str(error).split(":",1)[0]
            elapsed=time.monotonic()-started
            remaining=(timeout_seconds-elapsed if timeout_seconds is not None else 0)
            if not self._may_schema_retry(kind,error,remaining):
                raise
            record_generation_stage(kind,correlation_id,"schema_retry","started",0,
                                    attempt=2,**schema_log_fields(error))
            kwargs={**kwargs,"timeout_seconds":remaining}
            retry_started=time.monotonic()
            try:
                result=await generate(**kwargs)
            except Exception:
                record_generation_stage(kind,correlation_id,"schema_retry","failed",
                                        (time.monotonic()-retry_started)*1000,attempt=2)
                raise
            record_generation_stage(kind,correlation_id,"schema_retry","passed",
                                    (time.monotonic()-retry_started)*1000,attempt=2)
            return result

    async def generate_quiz(self, scope: LearningScope, context: VerifiedLearningContext,
                            *, topic: str, question_count: int, difficulty: str,
                            correlation_id: str | None = None, timeout_seconds: float | None = None,
                            deadline: float | None = None, temperature: float = 0.1,
                            max_tokens: int = 2048):
        await self._context(scope, context)
        correlation_id = correlation_id or uuid.uuid4().hex
        try:
            internal = await self._generate_with_schema_retry(
                "quiz",self.quiz_service.generate_grounded_quiz,correlation_id,
                timeout_seconds,dict(
                topic=topic, question_count=question_count, difficulty=difficulty,
                question_types=["mcq"], retrieved_context=context.text,
                source_metadata=context.source_metadata(), client_facing=False,
                correlation_id=correlation_id,
                temperature=temperature,max_tokens=max_tokens,
                **({"timeout_seconds":timeout_seconds} if timeout_seconds is not None else {}),
            ))
        except Exception:
            record_quiz_stage(correlation_id, "persistence", "not_reached", 0)
            raise
        for question in internal["questions"]:
            question["question_id"] = str(uuid.uuid4())
        quiz_id = str(uuid.uuid4())
        if deadline is not None and time.monotonic() >= deadline:
            record_quiz_stage(correlation_id,"persistence","not_reached",0)
            raise ValueError("LEARNING_GENERATION_TIMEOUT")
        await self._context(scope, context)
        if deadline is not None and time.monotonic() >= deadline:
            record_quiz_stage(correlation_id,"persistence","not_reached",0)
            raise ValueError("LEARNING_GENERATION_TIMEOUT")
        persistence_started = time.monotonic()
        record_quiz_stage(correlation_id, "persistence", "started", 0)
        try:
            await asyncio.to_thread(self.quizzes.save_quiz,QuizDefinitionRequest(
                quiz_id=quiz_id, course_id=scope.course_id, topic=topic,
                difficulty=difficulty, questions=internal["questions"], learning_context=context,
            ))
        except Exception:
            record_quiz_stage(
                correlation_id, "persistence", "failed",
                (time.monotonic() - persistence_started) * 1000)
            raise
        record_quiz_stage(
            correlation_id, "persistence", "passed",
            (time.monotonic() - persistence_started) * 1000)
        return {"quiz_id": quiz_id, "course_id": scope.course_id,
                **QuizService.to_public_result(internal)}

    async def prepare_flashcards(self, scope: LearningScope, context: VerifiedLearningContext,
                                 *, topic: str, count: int, difficulty: str,
                                 existing_pairs: set[tuple[str,str]] | None = None,
                                 correlation_id: str | None = None, timeout_seconds: float | None = None,
                                 deadline: float | None = None, temperature: float = 0.1,
                                 max_tokens: int = 1536):
        correlation_id=correlation_id or uuid.uuid4().hex
        await self._context(scope, context)
        internal = await self._generate_with_schema_retry(
            "flashcard",self.flashcard_service.generate_grounded_flashcards,correlation_id,
            timeout_seconds,dict(
            topic=topic, count=count, difficulty=difficulty, retrieved_context=context.text,
            source_metadata=context.source_metadata(),correlation_id=correlation_id,
            temperature=temperature,max_tokens=max_tokens,
            **({"timeout_seconds":timeout_seconds} if timeout_seconds is not None else {}),
        ))
        existing_pairs=existing_pairs or set()
        unique=[]; seen=set(existing_pairs)
        for card in internal["flashcards"]:
            pair=(" ".join(card["front_text"].casefold().split()),
                  " ".join(card["back_text"].casefold().split()))
            if pair not in seen:
                seen.add(pair); unique.append(card)
        if not unique:
            record_generation_stage("flashcard",correlation_id,"persistence","not_reached",0)
            raise ValueError("NO_NEW_FLASHCARDS")
        cards = [FlashcardRegistration(
            flashcard_id=str(uuid.uuid4()), course_id=scope.course_id, topic=topic,
            front_text=card["front_text"], back_text=card["back_text"],
            owner_id=scope.owner_id, learning_context=context,
        ) for card in unique]
        if deadline is not None and time.monotonic() >= deadline:
            record_generation_stage("flashcard",correlation_id,"persistence","not_reached",0)
            raise ValueError("LEARNING_GENERATION_TIMEOUT")
        await self._context(scope, context)
        if deadline is not None and time.monotonic() >= deadline:
            record_generation_stage("flashcard",correlation_id,"persistence","not_reached",0)
            raise ValueError("LEARNING_GENERATION_TIMEOUT")
        return {"course_id": scope.course_id,"requested_count":count,
                "created_count":len(cards),"skipped_duplicate_count":count-len(cards),"_cards":cards,"flashcards": [
            {"flashcard_id": card.flashcard_id, "front_text": card.front_text,
             "back_text": card.back_text, "topic": card.topic,
             "sources": context.source_metadata()} for card in cards]}

    async def generate_flashcards(self,*args,**kwargs):
        prepared=await self.prepare_flashcards(*args,**kwargs)
        cards=prepared.pop("_cards")
        correlation_id=kwargs.get("correlation_id") or "flashcard"
        started=time.monotonic(); record_generation_stage("flashcard",correlation_id,"persistence","started",0)
        try: await asyncio.to_thread(self.evidence.register_flashcards,cards)
        except Exception:
            record_generation_stage("flashcard",correlation_id,"persistence","failed",(time.monotonic()-started)*1000); raise
        record_generation_stage("flashcard",correlation_id,"persistence","passed",(time.monotonic()-started)*1000)
        return prepared
