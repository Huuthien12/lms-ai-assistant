"""Generation/persistence adapter for Thiện's verified retrieval caller.

Never expose VerifiedLearningContext as a client request model. Call only after
the shared guard and verified retrieval have succeeded. No arbitrary KB search
or provider payload is exposed to the integration caller.
"""
import uuid

from backend.services.ai.learning_context import LearningScope, VerifiedLearningContext
from backend.services.ai.quiz_service import QuizService
from quiz_lifecycle import QuizDefinitionRequest
from learning_evidence import FlashcardRegistration


class LearningGenerationService:
    def __init__(self, quiz_service, flashcard_service, quizzes, evidence, *, context_validator=None):
        self.quiz_service, self.flashcard_service = quiz_service, flashcard_service
        self.quizzes, self.evidence = quizzes, evidence
        self.context_validator = context_validator

    def _context(self, scope: LearningScope, context: VerifiedLearningContext):
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
            accepted = self.context_validator(scope, context)
        except Exception:
            raise ValueError("learning_context_rejected") from None
        if accepted is not True:
            raise ValueError("learning_context_rejected")

    async def generate_quiz(self, scope: LearningScope, context: VerifiedLearningContext,
                            *, topic: str, question_count: int, difficulty: str):
        self._context(scope, context)
        internal = await self.quiz_service.generate_grounded_quiz(
            topic=topic, question_count=question_count, difficulty=difficulty,
            question_types=["mcq"], retrieved_context=context.text,
            source_metadata=context.source_metadata(), client_facing=False,
        )
        for question in internal["questions"]:
            question["question_id"] = str(uuid.uuid4())
        quiz_id = str(uuid.uuid4())
        self._context(scope, context)
        self.quizzes.save_quiz(QuizDefinitionRequest(
            quiz_id=quiz_id, course_id=scope.course_id, topic=topic,
            difficulty=difficulty, questions=internal["questions"], learning_context=context,
        ))
        return {"quiz_id": quiz_id, "course_id": scope.course_id,
                **QuizService.to_public_result(internal)}

    async def generate_flashcards(self, scope: LearningScope, context: VerifiedLearningContext,
                                 *, topic: str, count: int, difficulty: str):
        self._context(scope, context)
        internal = await self.flashcard_service.generate_grounded_flashcards(
            topic=topic, count=count, difficulty=difficulty, retrieved_context=context.text,
            source_metadata=context.source_metadata(),
        )
        cards = [FlashcardRegistration(
            flashcard_id=str(uuid.uuid4()), course_id=scope.course_id, topic=topic,
            front_text=card["front_text"], back_text=card["back_text"],
            owner_id=scope.owner_id, learning_context=context,
        ) for card in internal["flashcards"]]
        self._context(scope, context)
        self.evidence.register_flashcards(cards)
        return {"course_id": scope.course_id, "flashcards": [
            {"flashcard_id": card.flashcard_id, "front_text": card.front_text,
             "back_text": card.back_text, "topic": card.topic,
             "sources": context.source_metadata()} for card in cards]}
