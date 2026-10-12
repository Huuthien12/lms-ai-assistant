"""Read-only orchestration over persisted quiz and mastery state."""
from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from backend.services.ai.learning_context import LearningScope, VerifiedLearningContext
from learning_access import learning_auth_unavailable, require_scope

from backend.services.ai.recommendation_service import RecommendationService
from learning_evidence import LearningEvidenceRepository


class LearningWorkflowRepository:
    def __init__(self, connect: Callable[[], Any], evidence: LearningEvidenceRepository):
        self.connect, self.evidence = connect, evidence

    def review(self, attempt_id: str, student_id: str, *, scope: LearningScope) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.cursor()
            attempt = cursor.execute(
                "SELECT quiz_id, student_id, status, course_id FROM dbo.QuizAttempts WHERE attempt_id=?", attempt_id
            ).fetchone()
            if attempt is None:
                raise ValueError("attempt_not_found")
            if attempt[1] != student_id:
                raise ValueError("attempt_not_owned")
            scope.require(attempt[1], attempt[3])
            if attempt[2] != "SUBMITTED":
                raise ValueError("attempt_not_submitted")
            row = cursor.execute("SELECT questions_json, context_json, course_id FROM dbo.QuizDefinitions WHERE quiz_id=?", attempt[0]).fetchone()
            if row is None:
                raise ValueError("quiz_not_found")
            if row[2] != attempt[3]:
                raise ValueError("learning_scope_forbidden")
            answers = cursor.execute("SELECT question_id, selected_option_id, correct FROM dbo.QuizAnswers WHERE attempt_id=?", attempt_id).fetchall()
        results = []
        questions = {q["question_id"]: q for q in json.loads(row[0])}
        context = VerifiedLearningContext.model_validate_json(row[1]) if row[1] else None
        if context:
            context.scope.require(scope.owner_id, scope.course_id)
        for question_id, selected, correct in answers:
            if not correct:
                question = questions.get(question_id)
                result = {"question_id": question_id, "correct": False,
                          "explanation_status": "unavailable"}
                if context and question:
                    result.update(explanation_status="available",
                                  explanation=question["explanation"],
                                  correct_option_id=question["correct_option_id"],
                                  selected_option_id=selected,
                                  sources=context.source_metadata())
                results.append(result)
        return {"attempt_id": attempt_id, "results": results}


def create_workflow_router(repository: LearningWorkflowRepository, recommendations: RecommendationService, scope_dependency=None) -> APIRouter:
    router = APIRouter(tags=["learning-workflow"])

    def fail(exc: ValueError) -> None:
        codes = {"attempt_not_found": 404, "quiz_not_found": 404,
                  "attempt_not_owned": 403, "attempt_not_submitted": 409,
                  "mastery_not_found": 404, "learning_scope_forbidden": 403}
        code = str(exc) if str(exc) in codes else "invalid_learning_request"
        raise HTTPException(codes.get(code, 422), detail={"code": code, "message": "Learning workflow request could not be completed."})

    @router.get("/quiz-attempts/{attempt_id}/review")
    def review(attempt_id: str, student_id: str,
               scope: LearningScope = Depends(scope_dependency or learning_auth_unavailable)) -> dict[str, Any]:
        try:
            return repository.review(attempt_id, student_id, scope=scope)
        except ValueError as exc:
            fail(exc)

    @router.get("/courses/{course_id}/recommendations")
    async def recommendation(course_id: str, student_id: str, topic: str | None = None,
                             scope: LearningScope = Depends(scope_dependency or learning_auth_unavailable)) -> dict[str, Any]:
        require_scope(scope, student_id, course_id)
        try:
            snapshots = repository.evidence.mastery_for(student_id, course_id, topic)
            result = [await recommendations.get_recommendations(snapshot, [item["topic"] for item in snapshots]) for snapshot in snapshots]
            return {"student_id": student_id, "course_id": course_id, "recommendations": result}
        except ValueError as exc:
            fail(exc)

    return router
