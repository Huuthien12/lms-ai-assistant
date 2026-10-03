import copy
import sys
from datetime import datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


sys.path.insert(0, str(Path(__file__).parents[1] / "lms-dlu-demo"))
from quiz_lifecycle import (  # noqa: E402
    QuizDefinitionRequest, QuizRepository, StartAttemptRequest, _trusted_questions,
    _validate_answers, create_quiz_router,
)
from backend.services.ai.grading_service import GradingService  # noqa: E402
from backend.services.ai.quiz_service import QuizService  # noqa: E402


QUESTIONS = [{
    "question_id": "q1", "question": "One?", "type": "mcq",
    "options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
    "correct_option_id": "a", "explanation": "Because.",
}]


class Row(tuple):
    pass


class MemoryConnection:
    """Small transactional DB-API fake: contract tests only, not SQL Server proof."""
    def __init__(self, state):
        self.state, self.snapshot, self.rowcount = state, None, 0

    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return MemoryCursor(self)
    def commit(self): self.snapshot = None
    def rollback(self):
        if self.snapshot is not None:
            self.state.clear(); self.state.update(self.snapshot); self.snapshot = None


class MemoryCursor:
    def __init__(self, conn): self.conn, self.result, self.rowcount = conn, None, 0
    def execute(self, sql, *params):
        values = params
        statement = " ".join(sql.split())
        state = self.conn.state
        if statement.startswith("SET XACT_ABORT"):
            self.conn.snapshot = copy.deepcopy(state)
        elif statement.startswith("INSERT INTO dbo.QuizDefinitions"):
            quiz_id, course_id, topic, difficulty, questions_json, created_at = values
            state["definitions"][quiz_id] = (course_id, topic, difficulty, questions_json, created_at)
        elif statement.startswith("SELECT course_id, topic, difficulty"):
            row = state["definitions"].get(values[0]); self.result = None if row is None else Row(row[:4])
        elif statement.startswith("SELECT attempt_id, started_at"):
            self.result = next((Row((a["id"], a["started_at"])) for a in state["attempts"].values()
                                if a["quiz_id"] == values[0] and a["student_id"] == values[1] and a["status"] == "IN_PROGRESS"), None)
        elif statement.startswith("INSERT INTO dbo.QuizAttempts"):
            attempt_id, quiz_id, student_id, course_id, started_at = values
            if any(a["quiz_id"] == quiz_id and a["student_id"] == student_id and a["status"] == "IN_PROGRESS" for a in state["attempts"].values()):
                raise RuntimeError("filtered unique index")
            state["attempts"][attempt_id] = {"id": attempt_id, "quiz_id": quiz_id, "student_id": student_id, "course_id": course_id, "status": "IN_PROGRESS", "started_at": started_at, "submitted_at": None}
        elif statement.startswith("SELECT quiz_id, status"):
            attempt = state["attempts"].get(values[0]); self.result = None if attempt is None else Row((attempt["quiz_id"], attempt["status"]))
        elif statement.startswith("INSERT INTO dbo.QuizAnswers"):
            if state.get("fail_answers"):
                raise RuntimeError("simulated write failure")
            attempt_id, question_id, selected, correct = values
            state["answers"][(attempt_id, question_id)] = (selected, correct)
        elif statement.startswith("UPDATE dbo.QuizAttempts"):
            attempt = state["attempts"].get(values[1])
            self.rowcount = int(attempt is not None and attempt["status"] == "IN_PROGRESS")
            if self.rowcount:
                attempt["status"], attempt["submitted_at"] = "SUBMITTED", values[0]
        return self
    def fetchone(self): return self.result


def state_repo():
    state = {"definitions": {}, "attempts": {}, "answers": {}}
    return state, QuizRepository(lambda: MemoryConnection(state))


def stored_quiz(repo):
    repo.save_quiz(QuizDefinitionRequest(quiz_id="quiz-1", course_id="course-1", topic="topic", difficulty="easy", questions=QUESTIONS))


def test_trusted_definition_and_recursive_public_contract():
    trusted = _trusted_questions(QUESTIONS)
    assert trusted[0]["correct_option_id"] == "a"
    public = QuizService.to_public_result({"questions": trusted})
    def walk(value):
        if isinstance(value, dict):
            assert not ({"correct_option_id", "correct_answer", "answer_key"} & value.keys())
            for item in value.values(): walk(item)
        elif isinstance(value, list):
            for item in value: walk(item)
    walk(public)


def test_start_is_idempotent_and_enforces_course_and_quiz():
    _, repo = state_repo(); stored_quiz(repo)
    request = StartAttemptRequest(quiz_id="quiz-1", course_id="course-1", student_id="student-1")
    first, second = repo.start(request), repo.start(request)
    assert first["status"] == "IN_PROGRESS" and first["attempt_id"] == second["attempt_id"]
    with pytest.raises(ValueError, match="course_mismatch"):
        repo.start(StartAttemptRequest(quiz_id="quiz-1", course_id="other", student_id="student-1"))
    with pytest.raises(ValueError, match="quiz_not_found"):
        repo.start(StartAttemptRequest(quiz_id="missing", course_id="course-1", student_id="student-1"))


def test_submit_persists_deterministic_grading_and_rejects_second_submit():
    state, repo = state_repo(); stored_quiz(repo)
    attempt = repo.start(StartAttemptRequest(quiz_id="quiz-1", course_id="course-1", student_id="student-1"))
    result = repo.submit(attempt["attempt_id"], [{"question_id": "q1", "selected_option_id": "a"}], GradingService())
    assert result["score_percent"] == 100 and state["answers"][(attempt["attempt_id"], "q1")] == ("a", True)
    assert state["attempts"][attempt["attempt_id"]]["status"] == "SUBMITTED"
    assert isinstance(state["attempts"][attempt["attempt_id"]]["submitted_at"], datetime)
    with pytest.raises(ValueError, match="already_submitted"):
        repo.submit(attempt["attempt_id"], [], GradingService())


@pytest.mark.parametrize("answers, code", [
    ([{"question_id": "missing", "selected_option_id": "a"}], "invalid_question"),
    ([{"question_id": "q1", "selected_option_id": "missing"}], "invalid_option"),
    ([{"question_id": "q1", "selected_option_id": "a"}, {"question_id": "q1", "selected_option_id": "b"}], "invalid_question"),
])
def test_submission_validation_rejects_untrusted_answers(answers, code):
    with pytest.raises(ValueError, match=code):
        _validate_answers(_trusted_questions(QUESTIONS), answers)


def test_submission_rollback_leaves_no_partial_answers_or_status_change():
    state, repo = state_repo(); stored_quiz(repo)
    attempt = repo.start(StartAttemptRequest(quiz_id="quiz-1", course_id="course-1", student_id="student-1"))
    state["fail_answers"] = True
    with pytest.raises(ValueError, match="persistence_failure"):
        repo.submit(attempt["attempt_id"], [{"question_id": "q1", "selected_option_id": "a"}], GradingService())
    assert state["answers"] == {}
    assert state["attempts"][attempt["attempt_id"]]["status"] == "IN_PROGRESS"


def test_definition_is_reloaded_by_a_fresh_repository_instance():
    state, repo = state_repo(); stored_quiz(repo)
    reconstructed = QuizRepository(lambda: MemoryConnection(state))
    assert reconstructed.quiz("quiz-1")["questions"][0]["correct_option_id"] == "a"


def test_http_contract_is_public_safe_and_sanitizes_errors():
    _, repo = state_repo()
    app = FastAPI(); app.include_router(create_quiz_router(repo))
    with TestClient(app) as client:
        created = client.post("/internal/quizzes", json={
            "quiz_id": "quiz-1", "course_id": "course-1", "topic": "topic",
            "difficulty": "easy", "questions": QUESTIONS,
        })
        assert created.status_code == 200
        assert "correct_option_id" not in created.text and "explanation" not in created.text
        missing = client.post("/quiz-attempts/missing/submit", json={"answers": []})
    assert missing.status_code == 404
    assert missing.json()["detail"] == {"code": "attempt_not_found", "message": "Quiz request could not be completed."}
