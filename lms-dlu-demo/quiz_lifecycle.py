"""SQL Server-backed, server-only quiz attempt lifecycle."""
from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from backend.services.ai.learning_context import LearningScope, VerifiedLearningContext
from learning_access import learning_auth_unavailable, require_scope

from backend.services.ai.grading_service import GradingService
from backend.services.ai.quiz_service import QuizService

TRUSTED_QUESTION_PROVENANCE_VERSION = 1


class QuizDefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quiz_id: str
    course_id: str
    topic: str
    difficulty: str
    questions: list[dict[str, Any]]
    learning_context: VerifiedLearningContext | None = None


class StartAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: str
    course_id: str
    quiz_id: str


class SubmittedAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str
    selected_option_id: str | None = None


class SubmitAttemptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
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
                IF COL_LENGTH('dbo.QuizDefinitions', 'context_json') IS NULL
                ALTER TABLE dbo.QuizDefinitions ADD context_json NVARCHAR(MAX) NULL;
            """)
            conn.commit()

    def save_quiz(self, data: QuizDefinitionRequest) -> None:
        if data.learning_context is not None and data.learning_context.scope.course_id != data.course_id:
            raise ValueError("learning_scope_forbidden")
        questions = _trusted_questions(data.questions, data.learning_context)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.connect() as conn:
            try:
                conn.cursor().execute(
                    "INSERT INTO dbo.QuizDefinitions "
                    "(quiz_id, course_id, topic, difficulty, questions_json, created_at, context_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    data.quiz_id, data.course_id, data.topic, data.difficulty,
                    json.dumps(questions), now,
                    data.learning_context.model_dump_json() if data.learning_context else None,
                )
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise ValueError("persistence_failure") from exc

    def quiz(self, quiz_id: str) -> dict[str, Any] | None:
        """Trusted server-only lookup; HTTP callers must use quiz_for_student."""
        with self.connect() as conn:
            return self._quiz_from_cursor(conn.cursor(), quiz_id)

    def quiz_for_student(self, quiz_id: str, scope: LearningScope) -> dict[str, Any]:
        quiz = self.quiz(quiz_id)
        if quiz is None:
            raise ValueError("quiz_not_found")
        scope.require(scope.owner_id, quiz["course_id"])
        if quiz["learning_context"]:
            quiz["learning_context"].scope.require(scope.owner_id, scope.course_id)
        return {"quiz_id": quiz_id, "course_id": quiz["course_id"],
                **QuizService.to_public_result(quiz)}

    @staticmethod
    def _quiz_from_cursor(cursor: Any, quiz_id: str) -> dict[str, Any] | None:
        row = cursor.execute(
            "SELECT course_id, topic, difficulty, questions_json, context_json FROM dbo.QuizDefinitions WHERE quiz_id=?", quiz_id
        ).fetchone()
        if row is None:
            return None
        return {"quiz_id": quiz_id, "course_id": row[0], "topic": row[1], "difficulty": row[2], "questions": json.loads(row[3]),
                "learning_context": VerifiedLearningContext.model_validate_json(row[4]) if row[4] else None}

    def start(self, request: StartAttemptRequest) -> dict[str, Any]:
        quiz = self.quiz(request.quiz_id)
        if quiz is None:
            raise ValueError("quiz_not_found")
        if quiz["course_id"] != request.course_id:
            raise ValueError("course_mismatch")
        if quiz["learning_context"] is not None:
            quiz["learning_context"].scope.require(request.student_id, request.course_id)
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
                cursor.execute("INSERT INTO dbo.QuizAttempts (attempt_id, quiz_id, student_id, course_id, status, started_at, submitted_at) VALUES (?, ?, ?, ?, 'IN_PROGRESS', ?, NULL)", attempt_id, request.quiz_id, request.student_id, request.course_id, now)
                conn.commit()
            except Exception as exc:
                conn.rollback()
                raise ValueError("persistence_failure") from exc
        return {"attempt_id": attempt_id, "status": "IN_PROGRESS", "started_at": now}

    def submit(self, attempt_id: str, answers: list[dict[str, Any]], grader: GradingService,
               *, scope: LearningScope) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                row = cursor.execute("SELECT quiz_id, status, student_id, course_id FROM dbo.QuizAttempts WITH (UPDLOCK, HOLDLOCK) WHERE attempt_id=?", attempt_id).fetchone()
                if row is None:
                    raise ValueError("attempt_not_found")
                scope.require(row[2], row[3])
                if row[1] != "IN_PROGRESS":
                    raise ValueError("already_submitted")
                quiz = self._quiz_from_cursor(cursor, row[0])
                if quiz is None:
                    raise ValueError("quiz_not_found")
                if quiz["course_id"] != row[3]:
                    raise ValueError("learning_scope_forbidden")
                _validate_answers(quiz["questions"], answers)
                graded = grader.grade(quiz["questions"], answers)
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                for result in graded["results"]:
                    cursor.execute("INSERT INTO dbo.QuizAnswers (attempt_id, question_id, selected_option_id, correct) VALUES (?, ?, ?, ?)", attempt_id, result["question_id"], result["selected_option_id"], result["correct"])
                if self.evidence is not None:
                    self.evidence.record_quiz(cursor, attempt_id=attempt_id, student_id=row[2], course_id=row[3], topic=quiz["topic"], results=graded["results"],
                                              topic_by_question=_verified_chapter_topics(quiz["questions"]))
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


def create_quiz_router(repository: QuizRepository, scope_dependency=None, writer_dependency=None) -> APIRouter:
    router = APIRouter(tags=["quiz"])
    grader = GradingService()

    def fail(exc: ValueError) -> None:
        codes = {"quiz_not_found": 404, "attempt_not_found": 404, "course_mismatch": 409,
                 "already_submitted": 409, "persistence_failure": 503, "learning_scope_forbidden": 403,
                 "invalid_quiz_definition": 422, "invalid_question": 422, "invalid_option": 422}
        code = str(exc) if str(exc) in codes else "invalid_quiz_request"
        raise HTTPException(codes.get(code, 422), detail={"code": code, "message": "Quiz request could not be completed."})

    @router.on_event("startup")
    def initialize() -> None:
        repository.ensure_schema()

    @router.post("/internal/quizzes", include_in_schema=False,
                 dependencies=[Depends(writer_dependency or learning_auth_unavailable)])
    def create_quiz(request: QuizDefinitionRequest) -> dict[str, Any]:
        try:
            repository.save_quiz(request)
        except ValueError as exc:
            fail(exc)
        return {"quiz_id": request.quiz_id, "course_id": request.course_id,
                **QuizService.to_public_result({"questions": _trusted_questions(request.questions)})}

    @router.post("/quizzes/{quiz_id}/attempts")
    def start_attempt(quiz_id: str, request: StartAttemptRequest,
                      scope: LearningScope = Depends(scope_dependency or learning_auth_unavailable)) -> dict[str, Any]:
        require_scope(scope, request.student_id, request.course_id)
        if request.quiz_id != quiz_id:
            fail(ValueError("quiz_not_found"))
        try:
            return repository.start(request)
        except ValueError as exc:
            fail(exc)

    @router.get("/quizzes/{quiz_id}")
    def read_quiz(quiz_id: str,
                  scope: LearningScope = Depends(scope_dependency or learning_auth_unavailable)) -> dict[str, Any]:
        try:
            return repository.quiz_for_student(quiz_id, scope)
        except ValueError as exc:
            fail(exc)

    @router.post("/quiz-attempts/{attempt_id}/submit")
    def submit_attempt(attempt_id: str, request: SubmitAttemptRequest,
                       scope: LearningScope = Depends(scope_dependency or learning_auth_unavailable)) -> dict[str, Any]:
        try:
            return repository.submit(attempt_id, [item.model_dump() for item in request.answers], grader, scope=scope)
        except ValueError as exc:
            fail(exc)

    return router


def _trusted_questions(questions: list[dict[str, Any]],
                       learning_context: VerifiedLearningContext | None = None) -> list[dict[str, Any]]:
    """Validate generated/internal quiz material and retain its stable question IDs."""
    try:
        # The domain validator preserves IDs; persisted artifacts require each ID.
        validated = QuizService.validate_and_parse_quiz({"questions": questions})["questions"]
    except ValueError as exc:
        raise ValueError("invalid_quiz_definition") from exc
    result = []
    ids: set[str] = set()
    for original, question in zip(questions, validated):
        question_id = original.get("question_id") if isinstance(original, dict) else None
        if not isinstance(question_id, str) or not question_id.strip() or question_id in ids:
            raise ValueError("invalid_quiz_definition")
        ids.add(question_id)
        source_metadata = original.get("source_metadata") if isinstance(original, dict) else None
        if isinstance(source_metadata, dict):
            source_metadata = [source_metadata]
        if isinstance(source_metadata, list):
            # Source IDs were checked by the generation validator; retain only the
            # stable locator required to map a post-submit explanation to its source.
            sources = [{"source_id": source["source_id"]} for source in source_metadata
                       if isinstance(source, dict) and isinstance(source.get("source_id"), str)]
            if sources:
                question["source_metadata"] = sources
        stored={"question_id": question_id, **question}
        provenance=_trusted_provenance(stored,learning_context)
        if provenance is not None:
            stored["trusted_provenance"]=provenance
        result.append(stored)
    return result


def _trusted_provenance(question: dict[str, Any],
                        learning_context: VerifiedLearningContext | None) -> dict[str, Any] | None:
    """Persist only source bindings independently verified by the issued context."""
    if learning_context is None:
        return None
    sources={source.source_id:source for source in learning_context.sources
             if source.provenance_status=="verified" and source.document_id
             and source.version and source.content_hash}
    bindings=[]
    for item in question.get("source_metadata",[]):
        source=sources.get(item.get("source_id")) if isinstance(item,dict) else None
        if source is not None:
            bindings.append({"source_id":source.source_id,"chapter_id":source.document_id,
                             "version":source.version,"content_hash":source.content_hash})
    if not bindings:
        return None
    unique={binding["source_id"]:binding for binding in bindings}
    return {"version":TRUSTED_QUESTION_PROVENANCE_VERSION,
            "bindings":[unique[key] for key in sorted(unique)]}


def _verified_chapter_topics(questions: list[dict[str, Any]]) -> dict[str, str]:
    """Use a chapter only when persisted P6 provenance has one exact binding."""
    result={}
    for question in questions:
        provenance=question.get("trusted_provenance") if isinstance(question,dict) else None
        bindings=provenance.get("bindings") if isinstance(provenance,dict) and provenance.get("version")==TRUSTED_QUESTION_PROVENANCE_VERSION else []
        chapters={item.get("chapter_id") for item in bindings if isinstance(item,dict) and isinstance(item.get("chapter_id"),str) and item["chapter_id"].strip()}
        if len(chapters)==1 and isinstance(question.get("question_id"),str): result[question["question_id"]]=next(iter(chapters))
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
