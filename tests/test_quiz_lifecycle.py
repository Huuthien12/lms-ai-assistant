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
    _validate_answers, _public_submission_result, create_quiz_router,
)
from backend.services.ai.grading_service import GradingService  # noqa: E402
from backend.services.ai.quiz_service import QuizService  # noqa: E402
from learning_evidence import FlashcardRegistration, FlashcardReviewRequest, LearningEvidenceRepository  # noqa: E402


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


def test_http_submit_response_projects_only_grading_facts():
    _, repo = state_repo()
    app = FastAPI(); app.include_router(create_quiz_router(repo))
    with TestClient(app) as client:
        client.post("/internal/quizzes", json={
            "quiz_id": "quiz-1", "course_id": "course-1", "topic": "topic",
            "difficulty": "easy", "questions": QUESTIONS,
        })
        attempt = client.post("/quizzes/quiz-1/attempts", json={
            "quiz_id": "quiz-1", "course_id": "course-1", "student_id": "student-1",
        }).json()
        response = client.post(f"/quiz-attempts/{attempt['attempt_id']}/submit", json={
            "answers": [{"question_id": "q1", "selected_option_id": "a"}],
        })
    assert response.status_code == 200
    assert response.json() == {
        "attempt_id": attempt["attempt_id"], "status": "SUBMITTED",
        "submitted_at": response.json()["submitted_at"], "score_percent": 100.0,
        "correct_count": 1, "total_questions": 1,
        "results": [{"question_id": "q1", "correct": True, "selected_option_id": "a"}],
    }


def test_submit_projection_drops_untrusted_grader_fields_recursively():
    public = _public_submission_result("attempt", datetime.now(), {
        "score_percent": 100, "correct_count": 1, "total_questions": 1,
        "results": [{"question_id": "q1", "correct": True, "selected_option_id": "a",
                     "correct_option_id": "a", "source_metadata": {"answer_key": "a"}}],
        "trusted_quiz_definition": {"correct_answer": "a"},
    })
    def walk(value):
        if isinstance(value, dict):
            assert not ({"correct_option_id", "correct_answer", "answer_key", "trusted_quiz_definition", "source_metadata", "explanation"} & value.keys())
            for nested in value.values(): walk(nested)
        elif isinstance(value, list):
            for nested in value: walk(nested)
    walk(public)


class EvidenceConnection:
    def __init__(self, state): self.state, self.snapshot = state, None
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def cursor(self): return EvidenceCursor(self)
    def commit(self): self.snapshot = None
    def rollback(self):
        if self.snapshot is not None: self.state.clear(); self.state.update(self.snapshot); self.snapshot = None


class EvidenceCursor:
    def __init__(self, conn): self.conn, self.result, self.rowcount = conn, None, 0
    def execute(self, sql, *values):
        sql, s = " ".join(sql.split()), self.conn.state
        if sql.startswith("SET XACT_ABORT"): self.conn.snapshot = copy.deepcopy(s)
        elif sql.startswith("SELECT course_id, topic FROM dbo.Flashcards"):
            row = s["cards"].get(values[0]); self.result = Row(row) if row else None
        elif sql.startswith("INSERT INTO dbo.Flashcards"):
            s["cards"][values[0]] = (values[1], values[2])
        elif sql.startswith("SELECT student_id, flashcard_id, rating FROM dbo.FlashcardReviews"):
            review = s["reviews"].get(values[0]); self.result = Row((review[0], review[1], review[2])) if review else None
        elif sql.startswith("INSERT INTO dbo.FlashcardReviews"):
            if s.get("fail_review"): raise RuntimeError("review failure")
            s["reviews"][values[0]] = values[1:]
        elif sql.startswith("INSERT INTO dbo.LearningEvents"):
            if s.get("fail_event"): raise RuntimeError("event failure")
            kind = "quiz" if "QUIZ_ANSWER" in sql else "flashcard"
            s["events"].append({"student_id": values[1], "course_id": values[2], "topic": values[3], "type": kind, "correct": values[5] if kind == "quiz" else None, "rating": values[5] if kind == "flashcard" else None})
        elif sql.startswith("SELECT event_type, correct, rating FROM dbo.LearningEvents"):
            events = [e for e in s["events"] if (e["student_id"], e["course_id"], e["topic"]) == values]
            self.result = [Row(("QUIZ_ANSWER" if e["type"] == "quiz" else "FLASHCARD_REVIEW", e["correct"], e["rating"])) for e in events]
        elif sql.startswith("UPDATE dbo.TopicMastery"):
            key = (values[5], values[6], values[7]); self.rowcount = int(key in s["mastery"])
            if self.rowcount: s["mastery"][key] = values[:5]
        elif sql.startswith("INSERT INTO dbo.TopicMastery"):
            s["mastery"][(values[1], values[2], values[3])] = values[4:9]
        elif sql.startswith("SELECT topic, mastery_score"):
            rows = [(topic, *value) for (student, course, topic), value in s["mastery"].items() if student == values[0] and course == values[1] and (len(values) == 2 or topic == values[2])]
            self.result = [Row(row) for row in rows]
        return self
    def fetchone(self): return self.result
    def fetchall(self): return self.result or []


def evidence_repo():
    state = {"cards": {}, "reviews": {}, "events": [], "mastery": {}}
    return state, LearningEvidenceRepository(lambda: EvidenceConnection(state))


def test_flashcard_registry_review_idempotency_and_server_scope():
    state, repo = evidence_repo()
    repo.register_flashcard(FlashcardRegistration(flashcard_id="card-1", course_id="course-1", topic="topic-1"))
    repo.register_flashcard(FlashcardRegistration(flashcard_id="card-1", course_id="course-1", topic="topic-1"))
    result = repo.review("card-1", FlashcardReviewRequest(student_id="student-1", rating="GOOD", review_id="review-1"))
    assert result["mastery"]["mastery_score"] == 75
    assert state["events"] == [{"student_id": "student-1", "course_id": "course-1", "topic": "topic-1", "type": "flashcard", "correct": None, "rating": "GOOD"}]
    assert repo.review("card-1", FlashcardReviewRequest(student_id="student-1", rating="GOOD", review_id="review-1"))["status"] == "RECORDED"
    assert len(state["reviews"]) == len(state["events"]) == 1
    with pytest.raises(ValueError, match="idempotency_conflict"):
        repo.review("card-1", FlashcardReviewRequest(student_id="student-2", rating="GOOD", review_id="review-1"))
    with pytest.raises(ValueError, match="idempotency_conflict"):
        repo.review("card-1", FlashcardReviewRequest(student_id="student-1", rating="EASY", review_id="review-1"))


def test_unknown_card_and_event_failure_roll_back_review_path():
    state, repo = evidence_repo()
    with pytest.raises(ValueError, match="flashcard_not_found"):
        repo.review("forged", FlashcardReviewRequest(student_id="student-1", rating="GOOD", review_id="review-1"))
    assert not state["reviews"] and not state["events"] and not state["mastery"]
    repo.register_flashcard(FlashcardRegistration(flashcard_id="card-1", course_id="course-1", topic="topic-1")); state["fail_event"] = True
    with pytest.raises(ValueError, match="persistence_failure"):
        repo.review("card-1", FlashcardReviewRequest(student_id="student-1", rating="GOOD", review_id="review-1"))
    assert not state["reviews"] and not state["events"] and not state["mastery"]


def test_review_request_forbids_client_mastery_and_scope_fields():
    with pytest.raises(Exception):
        FlashcardReviewRequest(student_id="student", rating="GOOD", review_id="review", course_id="forged")
