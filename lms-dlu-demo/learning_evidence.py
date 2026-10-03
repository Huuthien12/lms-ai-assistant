"""SQL Server persistence boundary for trusted learning evidence and mastery."""
from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.services.ai.mastery_service import MasteryService


class FlashcardRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    flashcard_id: str
    course_id: str
    topic: str


class FlashcardReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str
    rating: str
    review_id: str


class LearningEvidenceRepository:
    def __init__(self, connect: Callable[[], Any]):
        self.connect = connect
        self.mastery = MasteryService()

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.cursor().execute("""
                IF OBJECT_ID('dbo.Flashcards', 'U') IS NULL
                CREATE TABLE dbo.Flashcards (
                    flashcard_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    course_id NVARCHAR(128) NOT NULL,
                    topic NVARCHAR(256) NOT NULL,
                    created_at DATETIME2 NOT NULL
                );
                IF OBJECT_ID('dbo.FlashcardReviews', 'U') IS NULL
                CREATE TABLE dbo.FlashcardReviews (
                    review_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    student_id NVARCHAR(128) NOT NULL,
                    flashcard_id NVARCHAR(64) NOT NULL REFERENCES dbo.Flashcards(flashcard_id),
                    rating NVARCHAR(16) NOT NULL CHECK (rating IN ('AGAIN','HARD','GOOD','EASY')),
                    reviewed_at DATETIME2 NOT NULL
                );
                IF OBJECT_ID('dbo.LearningEvents', 'U') IS NULL
                CREATE TABLE dbo.LearningEvents (
                    event_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    student_id NVARCHAR(128) NOT NULL,
                    course_id NVARCHAR(128) NOT NULL,
                    topic NVARCHAR(256) NOT NULL,
                    event_type NVARCHAR(32) NOT NULL CHECK (event_type IN ('QUIZ_ANSWER','FLASHCARD_REVIEW')),
                    source_id NVARCHAR(128) NOT NULL,
                    correct BIT NULL,
                    rating NVARCHAR(16) NULL,
                    created_at DATETIME2 NOT NULL,
                    CONSTRAINT UX_LearningEvents_Source UNIQUE (event_type, source_id)
                );
                IF OBJECT_ID('dbo.TopicMastery', 'U') IS NULL
                CREATE TABLE dbo.TopicMastery (
                    mastery_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    student_id NVARCHAR(128) NOT NULL,
                    course_id NVARCHAR(128) NOT NULL,
                    topic NVARCHAR(256) NOT NULL,
                    mastery_score DECIMAL(5,2) NULL,
                    mastery_level NVARCHAR(16) NULL,
                    confidence_level NVARCHAR(16) NOT NULL,
                    evidence_count INT NOT NULL,
                    last_updated_at DATETIME2 NOT NULL,
                    CONSTRAINT UX_TopicMastery_Scope UNIQUE (student_id, course_id, topic)
                );
            """)
            conn.commit()

    def register_flashcard(self, card: FlashcardRegistration) -> None:
        if not all(isinstance(value, str) and value.strip() for value in (card.flashcard_id, card.course_id, card.topic)):
            raise ValueError("invalid_flashcard")
        with self.connect() as conn:
            try:
                existing = conn.cursor().execute("SELECT course_id, topic FROM dbo.Flashcards WHERE flashcard_id=?", card.flashcard_id).fetchone()
                if existing is not None:
                    if existing[0] == card.course_id and existing[1] == card.topic:
                        conn.commit(); return
                    raise ValueError("flashcard_conflict")
                conn.cursor().execute("INSERT INTO dbo.Flashcards (flashcard_id, course_id, topic, created_at) VALUES (?, ?, ?, ?)", card.flashcard_id, card.course_id, card.topic, _now())
                conn.commit()
            except ValueError:
                conn.rollback(); raise
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

    def record_quiz(self, cursor: Any, *, attempt_id: str, student_id: str, course_id: str, topic: str, results: list[dict[str, Any]]) -> None:
        for result in results:
            cursor.execute("INSERT INTO dbo.LearningEvents (event_id, student_id, course_id, topic, event_type, source_id, correct, rating, created_at) VALUES (?, ?, ?, ?, 'QUIZ_ANSWER', ?, ?, NULL, ?)", str(uuid.uuid4()), student_id, course_id, topic, f"{attempt_id}:{result['question_id']}", result["correct"], _now())
        self._recompute(cursor, student_id, course_id, topic)

    def review(self, flashcard_id: str, request: FlashcardReviewRequest) -> dict[str, Any]:
        if request.rating not in ("AGAIN", "HARD", "GOOD", "EASY") or not isinstance(request.student_id, str) or not request.student_id.strip() or not isinstance(request.review_id, str) or not request.review_id.strip():
            raise ValueError("invalid_flashcard_review")
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                card = cursor.execute("SELECT course_id, topic FROM dbo.Flashcards WITH (UPDLOCK, HOLDLOCK) WHERE flashcard_id=?", flashcard_id).fetchone()
                if card is None: raise ValueError("flashcard_not_found")
                existing = cursor.execute("SELECT review_id FROM dbo.FlashcardReviews WHERE review_id=?", request.review_id).fetchone()
                if existing is not None:
                    conn.commit(); return {"review_id": request.review_id, "status": "RECORDED"}
                now = _now()
                cursor.execute("INSERT INTO dbo.FlashcardReviews (review_id, student_id, flashcard_id, rating, reviewed_at) VALUES (?, ?, ?, ?, ?)", request.review_id, request.student_id, flashcard_id, request.rating, now)
                cursor.execute("INSERT INTO dbo.LearningEvents (event_id, student_id, course_id, topic, event_type, source_id, correct, rating, created_at) VALUES (?, ?, ?, ?, 'FLASHCARD_REVIEW', ?, NULL, ?, ?)", str(uuid.uuid4()), request.student_id, card[0], card[1], request.review_id, request.rating, now)
                mastery = self._recompute(cursor, request.student_id, card[0], card[1])
                conn.commit()
                return {"review_id": request.review_id, "status": "RECORDED", "mastery": _public_mastery(mastery)}
            except ValueError:
                conn.rollback(); raise
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

    def _recompute(self, cursor: Any, student_id: str, course_id: str, topic: str) -> dict[str, Any]:
        rows = cursor.execute("SELECT event_type, correct, rating FROM dbo.LearningEvents WHERE student_id=? AND course_id=? AND topic=? ORDER BY created_at, event_id", student_id, course_id, topic).fetchall()
        evidence = [{"student_id": student_id, "course_id": course_id, "topic": topic, "type": "quiz" if row[0] == "QUIZ_ANSWER" else "flashcard", **({"correct": bool(row[1])} if row[0] == "QUIZ_ANSWER" else {"rating": row[2]})} for row in rows]
        mastery = self.mastery.calculate_mastery(student_id=student_id, course_id=course_id, topic=topic, evidence=evidence)
        cursor.execute("UPDATE dbo.TopicMastery SET mastery_score=?, mastery_level=?, confidence_level=?, evidence_count=?, last_updated_at=? WHERE student_id=? AND course_id=? AND topic=?", mastery["mastery_score"], mastery["level"], mastery["confidence"], mastery["evidence_count"], _now(), student_id, course_id, topic)
        if cursor.rowcount == 0:
            cursor.execute("INSERT INTO dbo.TopicMastery (mastery_id, student_id, course_id, topic, mastery_score, mastery_level, confidence_level, evidence_count, last_updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", str(uuid.uuid4()), student_id, course_id, topic, mastery["mastery_score"], mastery["level"], mastery["confidence"], mastery["evidence_count"], _now())
        return mastery

    def mastery_for(self, student_id: str, course_id: str, topic: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as conn:
            sql = "SELECT topic, mastery_score, mastery_level, confidence_level, evidence_count, last_updated_at FROM dbo.TopicMastery WHERE student_id=? AND course_id=?" + (" AND topic=?" if topic else "")
            rows = conn.cursor().execute(sql, student_id, course_id, *([topic] if topic else [])).fetchall()
        if not rows: raise ValueError("mastery_not_found")
        return [{"topic": row[0], "mastery_score": float(row[1]) if row[1] is not None else None, "level": row[2], "confidence": row[3], "evidence_count": row[4], "last_updated_at": row[5]} for row in rows]


def create_learning_router(repository: LearningEvidenceRepository) -> APIRouter:
    router = APIRouter(tags=["learning"])
    def fail(exc: ValueError) -> None:
        status = {"flashcard_not_found": 404, "mastery_not_found": 404, "persistence_failure": 503}.get(str(exc), 422)
        raise HTTPException(status, detail={"code": str(exc), "message": "Learning request could not be completed."})
    @router.on_event("startup")
    def initialize() -> None: repository.ensure_schema()
    @router.post("/internal/flashcards", include_in_schema=False)
    def register(card: FlashcardRegistration) -> dict[str, str]:
        try: repository.register_flashcard(card)
        except ValueError as exc: fail(exc)
        return {"flashcard_id": card.flashcard_id, "status": "REGISTERED"}
    @router.post("/flashcards/{flashcard_id}/reviews")
    def review(flashcard_id: str, request: FlashcardReviewRequest) -> dict[str, Any]:
        try: return repository.review(flashcard_id, request)
        except ValueError as exc: fail(exc)
    @router.get("/courses/{course_id}/progress")
    def mastery(course_id: str, student_id: str, topic: str | None = None) -> dict[str, Any]:
        try: return {"student_id": student_id, "course_id": course_id, "topics": repository.mastery_for(student_id, course_id, topic)}
        except ValueError as exc: fail(exc)
    return router


def _now() -> datetime: return datetime.now(timezone.utc).replace(tzinfo=None)
def _public_mastery(mastery: dict[str, Any]) -> dict[str, Any]: return {key: mastery[key] for key in ("topic", "mastery_score", "level", "confidence", "evidence_count")}
