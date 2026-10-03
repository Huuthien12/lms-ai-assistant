"""Read-only orchestration over persisted quiz and mastery state."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.services.ai.recommendation_service import RecommendationService
from learning_evidence import LearningEvidenceRepository


class LearningWorkflowRepository:
    def __init__(self, connect: Callable[[], Any], evidence: LearningEvidenceRepository):
        self.connect, self.evidence = connect, evidence

    def review(self, attempt_id: str, student_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.cursor()
            attempt = cursor.execute(
                "SELECT quiz_id, student_id FROM dbo.QuizAttempts WHERE attempt_id=? AND status='SUBMITTED'", attempt_id
            ).fetchone()
            if attempt is None:
                raise ValueError("attempt_not_found")
            if attempt[1] != student_id:
                raise ValueError("attempt_not_owned")
            row = cursor.execute("SELECT questions_json FROM dbo.QuizDefinitions WHERE quiz_id=?", attempt[0]).fetchone()
            if row is None:
                raise ValueError("quiz_not_found")
            answers = cursor.execute("SELECT question_id, selected_option_id, correct FROM dbo.QuizAnswers WHERE attempt_id=?", attempt_id).fetchall()
        results = []
        for question_id, selected, correct in answers:
            if not correct:
                # Grounded context was not persisted with the quiz, so an AI
                # explanation is deliberately unavailable rather than invented.
                results.append({"question_id": question_id, "correct": False,
                                "explanation_status": "unavailable"})
        return {"attempt_id": attempt_id, "results": results}


def create_workflow_router(repository: LearningWorkflowRepository, recommendations: RecommendationService) -> APIRouter:
    router = APIRouter(tags=["learning-workflow"])

    def fail(exc: ValueError) -> None:
        code = str(exc)
        status = {"attempt_not_found": 404, "quiz_not_found": 404,
                  "attempt_not_owned": 403, "mastery_not_found": 404}.get(code, 422)
        raise HTTPException(status, detail={"code": code, "message": "Learning workflow request could not be completed."})

    @router.get("/quiz-attempts/{attempt_id}/review")
    def review(attempt_id: str, student_id: str) -> dict[str, Any]:
        try:
            return repository.review(attempt_id, student_id)
        except ValueError as exc:
            fail(exc)

    @router.get("/courses/{course_id}/recommendations")
    async def recommendation(course_id: str, student_id: str, topic: str | None = None) -> dict[str, Any]:
        try:
            snapshots = repository.evidence.mastery_for(student_id, course_id, topic)
            result = [await recommendations.get_recommendations(snapshot, [item["topic"] for item in snapshots]) for snapshot in snapshots]
            return {"student_id": student_id, "course_id": course_id, "recommendations": result}
        except ValueError as exc:
            fail(exc)

    return router
