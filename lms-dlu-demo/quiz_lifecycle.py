"""SQL Server-backed, server-only quiz attempt lifecycle."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai.grading_service import GradingService
from backend.services.ai.quiz_service import QuizService


class QuizDefinitionRequest(BaseModel):
    quiz_id: str
    course_id: str
    topic: str
    difficulty: str
    questions: list[dict[str, Any]]


class StartAttemptRequest(BaseModel):
    student_id: str
    course_id: str
    quiz_id: str


class SubmittedAnswer(BaseModel):
    question_id: str
    selected_option_id: str | None = None


class SubmitAttemptRequest(BaseModel):
    answers: list[SubmittedAnswer] = Field(default_factory=list)


class QuizRepository:
    def __init__(self, connect: Callable[[], Any], evidence: Any = None):
        self.connect = connect
        self.evidence = evidence

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                IF OBJECT_ID('dbo.QuizDefinitions', 'U') IS NULL
                CREATE TABLE dbo.QuizDefinitions (
                    quiz_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    course_id NVARCHAR(128) NOT NULL,
                    topic NVARCHAR(256) NOT NULL,
                    difficulty NVARCHAR(32) NOT NULL,
                    questions_json NVARCHAR(MAX) NOT NULL,
                    created_at DATETIME2 NOT NULL
                );
                IF OBJECT_ID('dbo.QuizAttempts', 'U') IS NULL
                CREATE TABLE dbo.QuizAttempts (
                    attempt_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    quiz_id NVARCHAR(64) NOT NULL REFERENCES dbo.QuizDefinitions(quiz_id),
                    student_id NVARCHAR(128) NOT NULL,
                    course_id NVARCHAR(128) NOT NULL,
                    status NVARCHAR(16) NOT NULL CHECK (status IN ('IN_PROGRESS','SUBMITTED')),
                    started_at DATETIME2 NOT NULL,
                    submitted_at DATETIME2 NULL
                );
                IF NOT EXISTS (
                    SELECT 1 FROM sys.indexes
                    WHERE object_id = OBJECT_ID(N'dbo.QuizAttempts')
                      AND name = N'UX_QuizAttempts_Active'
                )
                CREATE UNIQUE INDEX UX_QuizAttempts_Active ON dbo.QuizAttempts(quiz_id, student_id)
                WHERE status = 'IN_PROGRESS';
                IF OBJECT_ID('dbo.QuizAnswers', 'U') IS NULL
                CREATE TABLE dbo.QuizAnswers (
                    attempt_id NVARCHAR(64) NOT NULL REFERENCES dbo.QuizAttempts(attempt_id),
                    question_id NVARCHAR(128) NOT NULL,
                    selected_option_id NVARCHAR(128) NULL,
                    correct BIT NOT NULL,
                    CONSTRAINT PK_QuizAnswers PRIMARY KEY (attempt_id, question_id)
                );
            """)
            conn.commit()

    def save_quiz(self, data: QuizDefinitionRequest) -> None:
        questions = _trusted_questions(data.questions)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.connect() as conn:
            try:
                conn.cursor().execute(
                    "INSERT INTO dbo.QuizDefinitions "
                    "(quiz_id, course_id, topic, difficulty, questions_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    data.quiz_id, data.course_id, data.topic, data.difficulty,
                    json.dumps(questions), now,
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise ValueError("persistence_failure") from exc

    def quiz(self, quiz_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            return self._quiz_from_cursor(conn.cursor(), quiz_id)

    @staticmethod
    def _quiz_from_cursor(cursor: Any, quiz_id: str) -> dict[str, Any] | None:
        row = cursor.execute(
            "SELECT course_id, topic, difficulty, questions_json FROM dbo.QuizDefinitions WHERE quiz_id=?", quiz_id
        ).fetchone()
        if row is None:
            return None
        return {"quiz_id": quiz_id, "course_id": row[0], "topic": row[1], "difficulty": row[2], "questions": json.loads(row[3])}

    def start(self, request: StartAttemptRequest) -> dict[str, Any]:
        quiz = self.quiz(request.quiz_id)
        if quiz is None:
            raise ValueError("quiz_not_found")
        if quiz["course_id"] != request.course_id:
            raise ValueError("course_mismatch")
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                row = cursor.execute(
                    "SELECT attempt_id, started_at FROM dbo.QuizAttempts WITH (UPDLOCK, HOLDLOCK) "
                    "WHERE quiz_id=? AND student_id=? AND status='IN_PROGRESS'",
                    request.quiz_id, request.student_id,
                ).fetchone()
                if row is not None:
                    conn.commit()
                    return {"attempt_id": row[0], "status": "IN_PROGRESS", "started_at": row[1]}
                attempt_id, now = str(uuid.uuid4()), datetime.now(timezone.utc).replace(tzinfo=None)
                cursor.execute("INSERT INTO dbo.QuizAttempts VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, NULL)", attempt_id, request.quiz_id, request.student_id, request.course_id, now)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise ValueError("persistence_failure") from exc
        return {"attempt_id": attempt_id, "status": "IN_PROGRESS", "started_at": now}

    def submit(self, attempt_id: str, answers: list[dict[str, Any]], grader: GradingService) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                row = cursor.execute("SELECT quiz_id, status, student_id, course_id FROM dbo.QuizAttempts WITH (UPDLOCK, HOLDLOCK) WHERE attempt_id=?", attempt_id).fetchone()
                if row is None:
                    raise ValueError("attempt_not_found")
                if row[1] != "IN_PROGRESS":
                    raise ValueError("already_submitted")
                quiz = self._quiz_from_cursor(cursor, row[0])
                if quiz is None:
                    raise ValueError("quiz_not_found")
                _validate_answers(quiz["questions"], answers)
                graded = grader.grade(quiz["questions"], answers)
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for result in graded["results"]:
                    cursor.execute("INSERT INTO dbo.QuizAnswers VALUES (?, ?, ?, ?)", attempt_id, result["question_id"], result["selected_option_id"], result["correct"])
                if self.evidence is not None:
                    self.evidence.record_quiz(cursor, attempt_id=attempt_id, student_id=row[2], course_id=row[3], topic=quiz["topic"], results=graded["results"])
                cursor.execute("UPDATE dbo.QuizAttempts SET status='SUBMITTED', submitted_at=? WHERE attempt_id=? AND status='IN_PROGRESS'", now, attempt_id)
                if cursor.rowcount != 1:
                    raise ValueError("already_submitted")
                conn.commit()
            except ValueError:
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise ValueError("persistence_failure") from None
        return _public_submission_result(attempt_id, now, graded)


def create_quiz_router(repository: QuizRepository) -> APIRouter:
    router = APIRouter(tags=["quiz"])
    grader = GradingService()

    def fail(exc: ValueError) -> None:
        codes = {"quiz_not_found": 404, "attempt_not_found": 404, "course_mismatch": 409,
                 "already_submitted": 409, "persistence_failure": 503}
        raise HTTPException(codes.get(str(exc), 422), detail={"code": str(exc), "message": "Quiz request could not be completed."})

    @router.on_event("startup")
    def initialize() -> None:
        repository.ensure_schema()

    @router.post("/internal/quizzes", include_in_schema=False)
    def create_quiz(request: QuizDefinitionRequest) -> dict[str, Any]:
        try:
            repository.save_quiz(request)
        except ValueError as exc:
            fail(exc)
        return {"quiz_id": request.quiz_id, "course_id": request.course_id,
                **QuizService.to_public_result({"questions": _trusted_questions(request.questions)})}

    @router.post("/quizzes/{quiz_id}/attempts")
    def start_attempt(quiz_id: str, request: StartAttemptRequest) -> dict[str, Any]:
        if request.quiz_id != quiz_id:
            fail(ValueError("quiz_not_found"))
        try:
            return repository.start(request)
        except ValueError as exc:
            fail(exc)

    @router.post("/quiz-attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: str, request: SubmitAttemptRequest) -> dict[str, Any]:
        try:
            return repository.submit(attempt_id, [item.model_dump() for item in request.answers], grader)
        except ValueError as exc:
            fail(exc)

    return router


def _trusted_questions(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate generated/internal quiz material and retain its stable question IDs."""
    try:
        # The validator deliberately allowlists only quiz content; question_id is
        # lifecycle metadata and is checked separately below.
        validated = QuizService.validate_and_parse_quiz(None, {"questions": questions})["questions"]
    except ValueError as exc:
        raise ValueError("invalid_quiz_definition") from exc
    result = []
    ids: set[str] = set()
    for original, question in zip(questions, validated):
        question_id = original.get("question_id") if isinstance(original, dict) else None
        if not isinstance(question_id, str) or not question_id.strip() or question_id in ids:
            raise ValueError("invalid_quiz_definition")
        ids.add(question_id)
        result.append({"question_id": question_id, **question})
    return result


def _validate_answers(questions: list[dict[str, Any]], answers: list[dict[str, Any]]) -> None:
    known = {question["question_id"]: {option["id"] for option in question["options"]} for question in questions}
    submitted: set[str] = set()
    for answer in answers:
        question_id = answer.get("question_id")
        if not isinstance(question_id, str) or question_id not in known or question_id in submitted:
            raise ValueError("invalid_question")
        submitted.add(question_id)
        selected = answer.get("selected_option_id")
        if selected is not None and (not isinstance(selected, str) or selected not in known[question_id]):
            raise ValueError("invalid_option")


def _public_submission_result(attempt_id: str, submitted_at: datetime, graded: dict[str, Any]) -> dict[str, Any]:
    """Allowlist client-visible grading facts; trusted quiz data never crosses this boundary."""
    return {
        "attempt_id": attempt_id,
        "status": "SUBMITTED",
        "submitted_at": submitted_at,
        "score_percent": graded["score_percent"],
        "correct_count": graded["correct_count"],
        "total_questions": graded["total_questions"],
        "results": [
            {"question_id": result["question_id"], "correct": result["correct"],
             "selected_option_id": result["selected_option_id"]}
            for result in graded["results"]
        ],
    }
