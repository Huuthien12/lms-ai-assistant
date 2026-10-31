"""Service/HTTP composition with a transactional DB fake; not live SQL or auth."""
import copy
import json
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from test_quiz_lifecycle import (
    QUESTIONS, SCOPE, MemoryConnection, MemoryCursor, EvidenceCursor,
    QuizRepository, GradingService, QuizService, StartAttemptRequest,
    QuizDefinitionRequest, LearningEvidenceRepository, LearningWorkflowRepository,
    FlashcardRegistration, FlashcardReviewRequest, create_quiz_router,
    create_workflow_router, state_repo, stored_quiz, evidence_repo,
)
from backend.services.ai.learning_context import LearningScope, LearningSource, VerifiedLearningContext
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.recommendation_service import RecommendationService
from learning_evidence import create_learning_router
from learning_generation import LearningGenerationService


def context():
    return VerifiedLearningContext(
        scope=SCOPE, kb_id="server-kb", retrieval_id="retrieval-1", text="One is A.",
        sources=(LearningSource(source_id="source-1", chunk_id="chunk-1", version="v1"),),
    )


class CombinedCursor(MemoryCursor):
    def execute(self, sql, *values):
        statement = " ".join(sql.split())
        state = self.conn.state
        if any(table in statement for table in ("dbo.LearningEvents", "dbo.TopicMastery", "dbo.Flashcards", "dbo.FlashcardReviews")):
            other = EvidenceCursor(self.conn).execute(sql, *values)
            self.result, self.rowcount = other.result, other.rowcount
            return self
        if statement.startswith("SELECT quiz_id, student_id, status, course_id"):
            a = state["attempts"].get(values[0])
            self.result = (a["quiz_id"], a["student_id"], a["status"], a["course_id"]) if a else None
            return self
        if statement.startswith("SELECT questions_json"):
            q = state["definitions"].get(values[0])
            self.result = (q[3], q[4], q[0]) if q else None
            return self
        if statement.startswith("SELECT question_id, selected_option_id, correct"):
            self.result = [(qid, selected, correct) for (aid, qid), (selected, correct)
                           in state["answers"].items() if aid == values[0]]
            return self
        return super().execute(sql, *values)

    def fetchall(self):
        return self.result or []


class CombinedConnection(MemoryConnection):
    def cursor(self):
        return CombinedCursor(self)


def composition():
    state = {"definitions": {}, "attempts": {}, "answers": {}, "cards": {},
             "reviews": {}, "events": [], "mastery": {}}
    connect = lambda: CombinedConnection(state)
    evidence = LearningEvidenceRepository(connect)
    quizzes = QuizRepository(connect, evidence)
    provider = Mock()
    grounded_questions = copy.deepcopy(QUESTIONS)
    grounded_questions[0].update(
        question=QuizService.GROUNDING_QUESTION_PREFIX + "One is ____.",
        grounding_evidence="One is A.",
    )
    provider.generate = AsyncMock(return_value=LLMResult(
        "success", "test", "test", json.dumps({"questions": grounded_questions}), 0))
    generation = LearningGenerationService(QuizService(provider), FlashcardService(provider), quizzes, evidence,
        context_validator=lambda scope, ctx: True)  # Test-only synthetic approval.
    return state, provider, generation, quizzes, evidence, LearningWorkflowRepository(connect, evidence)


def assert_public(value):
    if isinstance(value, dict):
        assert not {"correct_option_id", "correct_answer", "answer_key", "explanation",
                    "source_metadata", "learning_context", "is_correct"}.intersection(value)
        for child in value.values():
            assert_public(child)
    elif isinstance(value, list):
        for child in value:
            assert_public(child)


@pytest.mark.asyncio
@pytest.mark.parametrize("selected,score", [("a", 100), ("b", 0), (None, 0)])
async def test_generate_persist_submit_evidence_mastery_and_review(selected, score):
    state, provider, gen, quizzes, evidence, workflow = composition()
    public = await gen.generate_quiz(SCOPE, context(), topic="topic", question_count=1, difficulty="easy")
    assert_public(public)
    qid = public["questions"][0]["question_id"]
    persisted = quizzes.quiz(public["quiz_id"])
    assert persisted["learning_context"] == context()
    assert persisted["questions"][0]["question_id"] == qid
    attempt = quizzes.start(StartAttemptRequest(quiz_id=public["quiz_id"], student_id=SCOPE.owner_id, course_id=SCOPE.course_id))
    with pytest.raises(ValueError, match="attempt_not_submitted"):
        workflow.review(attempt["attempt_id"], SCOPE.owner_id, scope=SCOPE)
    calls = provider.generate.await_count
    result = quizzes.submit(attempt["attempt_id"], [{"question_id": qid, "selected_option_id": selected}], GradingService(), scope=SCOPE)
    assert result["score_percent"] == score
    assert provider.generate.await_count == calls  # No LLM grading/review call.
    assert evidence.mastery_for(SCOPE.owner_id, SCOPE.course_id)[0]["mastery_score"] == score
    review = workflow.review(attempt["attempt_id"], SCOPE.owner_id, scope=SCOPE)
    if selected != "a":
        assert review["results"][0]["explanation_status"] == "available"
        assert review["results"][0]["sources"] == context().source_metadata()
        assert review["results"][0]["sources"][0]["provenance_status"] == "unverified"
    with pytest.raises(ValueError, match="already_submitted"):
        quizzes.submit(attempt["attempt_id"], [], GradingService(), scope=SCOPE)
    assert len(state["events"]) == 1


@pytest.mark.asyncio
async def test_mixed_semantic_failure_prevents_quiz_persistence():
    state, provider, gen, _, _, _ = composition()
    supported = json.loads(provider.generate.return_value.content)["questions"][0]
    unsupported = {
        **copy.deepcopy(supported),
        "question": QuizService.GROUNDING_QUESTION_PREFIX + "Two is ____.",
        "options": [{"id": "a", "text": "C"}, {"id": "b", "text": "D"}],
        "grounding_evidence": "Two is C.",
    }
    provider.generate.return_value.content = json.dumps({
        "questions": [supported, unsupported],
    })
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await gen.generate_quiz(
            SCOPE, context(), topic="topic", question_count=2, difficulty="easy")
    assert state == before


@pytest.mark.asyncio
async def test_flashcard_generation_persists_content_and_review_evidence():
    state, provider, gen, _, evidence, _ = composition()
    provider.generate.return_value.content = json.dumps({"flashcards": [{
        "front": "One?", "back": "A", "topic": "topic", "difficulty": "easy",
        "source_metadata": {"source_id": "forged"}}]})
    result = await gen.generate_flashcards(SCOPE, context(), topic="topic", count=1, difficulty="easy")
    card_id = result["flashcards"][0]["flashcard_id"]
    fresh = LearningEvidenceRepository(evidence.connect)
    card = fresh.flashcard(card_id, SCOPE)
    assert card["front_text"] == "One?" and card["back_text"] == "A"
    assert card["learning_context"]["sources"][0]["version"] == "v1"
    assert "forged" not in json.dumps(card)
    reviewed = fresh.review(card_id, FlashcardReviewRequest(student_id=SCOPE.owner_id, rating="GOOD", review_id="review"), scope=SCOPE)
    assert reviewed["mastery"]["mastery_score"] == 75
    assert len(state["events"]) == 1


@pytest.mark.asyncio
async def test_prepare_flashcards_validates_without_persistence():
    state, provider, gen, _, _, _ = composition()
    provider.generate.return_value.content = json.dumps({"flashcards": [{
        "front": "One?", "back": "A", "topic": "topic", "difficulty": "easy"}]})
    before=copy.deepcopy(state)
    prepared=await gen.prepare_flashcards(SCOPE,context(),topic="topic",count=1,difficulty="easy")
    assert prepared["_cards"] and state==before


@pytest.mark.asyncio
async def test_prepare_flashcards_invalid_output_writes_nothing():
    state, provider, gen, _, _, _ = composition()
    provider.generate.return_value.content=json.dumps({"flashcards":[{"front":"","back":"A","topic":"topic","difficulty":"easy"}]})
    before=copy.deepcopy(state)
    with pytest.raises(ValueError,match="INVALID_FLASHCARD_SCHEMA"):
        await gen.prepare_flashcards(SCOPE,context(),topic="topic",count=1,difficulty="easy")
    assert state==before


@pytest.mark.parametrize("scope", [LearningScope(owner_id="attacker", course_id="course-1"),
                                   LearningScope(owner_id="student-1", course_id="other")])
def test_submit_checks_owner_and_course_before_grading_or_mutation(scope):
    state, quizzes = state_repo()
    stored_quiz(quizzes)
    attempt = quizzes.start(StartAttemptRequest(quiz_id="quiz-1", student_id=SCOPE.owner_id, course_id=SCOPE.course_id))
    before = copy.deepcopy(state)
    grader = Mock()
    with pytest.raises(ValueError, match="learning_scope_forbidden"):
        quizzes.submit(attempt["attempt_id"], [], grader, scope=scope)
    grader.grade.assert_not_called()
    assert state == before


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quiz", "flashcards"])
@pytest.mark.parametrize("validator", [None, lambda *_: False, lambda *_: {"verified": True}])
async def test_shape_and_verified_flags_do_not_authorize_generation(kind, validator):
    _, provider, gen, _, _, _ = composition()
    gen.context_validator = validator
    args = {"topic": "topic", "difficulty": "easy", "question_count" if kind == "quiz" else "count": 1}
    with pytest.raises(ValueError, match="learning_context"):
        await getattr(gen, "generate_" + kind)(SCOPE, context(), **args)
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_scope_mismatch_and_revocation_do_not_persist_artifacts():
    state, provider, gen, _, _, _ = composition()
    with pytest.raises(ValueError, match="learning_scope_forbidden"):
        await gen.generate_quiz(LearningScope(owner_id="other", course_id="course-1"), context(), topic="topic", question_count=1, difficulty="easy")
    provider.generate.assert_not_awaited()
    gen.context_validator = Mock(side_effect=[True, False])
    with pytest.raises(ValueError, match="learning_context_rejected"):
        await gen.generate_quiz(SCOPE, context(), topic="topic", question_count=1, difficulty="easy")
    assert state["definitions"] == {}


@pytest.mark.parametrize("method,path,body", [
    ("post", "/internal/quizzes", {}), ("post", "/internal/flashcards", {}),
    ("post", "/quizzes/q/attempts", {}), ("post", "/quiz-attempts/a/submit", {"answers": []}),
    ("post", "/flashcards/f/reviews", {}),
    ("get", "/quizzes/q", None), ("get", "/flashcards/f", None),
    ("get", "/courses/course-1/progress?student_id=student-1", None),
    ("get", "/courses/course-1/recommendations?student_id=student-1", None),
    ("get", "/quiz-attempts/a/review?student_id=student-1", None),
])
def test_all_learning_routes_deny_when_shared_auth_is_missing(method, path, body):
    repo = Mock()
    app = FastAPI()
    app.include_router(create_quiz_router(repo))
    app.include_router(create_learning_router(repo))
    app.include_router(create_workflow_router(repo, Mock()))
    response = TestClient(app).request(method, path, **({"json": body} if body is not None else {}))
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "learning_auth_not_configured"
    assert repo.mock_calls == []


def test_authenticated_http_rejects_student_spoof_and_client_score():
    _, repo = state_repo()
    app = FastAPI()
    app.include_router(create_quiz_router(repo, scope_dependency=lambda: SCOPE))
    client = TestClient(app)
    assert client.post("/quizzes/q/attempts", json={"quiz_id": "q", "course_id": "course-1", "student_id": "other"}).status_code == 403
    assert client.post("/quiz-attempts/a/submit", json={"answers": [], "score": 100}).status_code == 422
    assert client.post("/quiz-attempts/a/submit", json={"answers": [{"question_id": "q1", "selected_option_id": "a", "answer_key": "a"}]}).status_code == 422


def test_flashcard_batch_conflict_rolls_back_and_legacy_rows_fail_controlled():
    state, repo = evidence_repo()
    card = FlashcardRegistration(flashcard_id="existing", course_id="course-1", topic="topic",
                                front_text="front", back_text="back", owner_id="student-1")
    repo.register_flashcard(card)
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="flashcard_conflict"):
        repo.register_flashcards([card.model_copy(update={"flashcard_id": "new"}), card.model_copy(update={"back_text": "changed"})])
    assert state == before
    state["cards"]["legacy"] = ("course-1", "topic", None)
    with pytest.raises(ValueError, match="flashcard_context_unavailable"):
        repo.flashcard("legacy", SCOPE)


@pytest.mark.asyncio
async def test_evidence_failure_rolls_back_quiz_answers_and_status():
    state, _, gen, quizzes, _, _ = composition()
    public = await gen.generate_quiz(SCOPE, context(), topic="topic", question_count=1, difficulty="easy")
    attempt = quizzes.start(StartAttemptRequest(quiz_id=public["quiz_id"], student_id=SCOPE.owner_id, course_id=SCOPE.course_id))
    state["fail_event"] = True
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="persistence_failure"):
        quizzes.submit(attempt["attempt_id"], [], GradingService(), scope=SCOPE)
    assert state == before


@pytest.mark.asyncio
async def test_empty_context_never_calls_provider():
    _, provider, gen, _, _, _ = composition()
    with pytest.raises(ValueError, match="INSUFFICIENT_GROUNDED_CONTEXT"):
        await gen.generate_quiz(SCOPE, context().model_copy(update={"sources": ()}), topic="topic", question_count=1, difficulty="easy")
    provider.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_expired_generation_deadline_never_persists_quiz():
    state,_,gen,_,_,_=composition()
    with pytest.raises(ValueError,match="^LEARNING_GENERATION_TIMEOUT$"):
        await gen.generate_quiz(SCOPE,context(),topic="topic",question_count=1,
                                difficulty="easy",deadline=0)
    assert state["definitions"]=={}


@pytest.mark.asyncio
async def test_quiz_schema_failure_retries_once_then_persists_valid_result():
    state,provider,gen,_,_,_=composition()
    valid=provider.generate.return_value
    provider.generate.side_effect=[LLMResult("success","test","test","not-json",0),valid]
    result=await gen.generate_quiz(SCOPE,context(),topic="topic",question_count=1,
                                   difficulty="easy",timeout_seconds=10)
    assert result["quiz_id"] in state["definitions"]
    assert provider.generate.await_count==2


@pytest.mark.asyncio
async def test_flashcard_schema_failure_retries_once_then_persists_valid_result():
    state,provider,gen,_,_,_=composition()
    valid=LLMResult("success","test","test",json.dumps({"flashcards":[{
        "front_text":"One?","back_text":"A","topic":"topic","difficulty":"easy"}]}),0)
    provider.generate.side_effect=[LLMResult("success","test","test","not-json",0),valid]
    result=await gen.generate_flashcards(SCOPE,context(),topic="topic",count=1,
                                         difficulty="easy",timeout_seconds=10)
    assert result["flashcards"][0]["flashcard_id"] in state["cards"]
    assert provider.generate.await_count==2


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [LearningScope(owner_id="other", course_id="course-1"),
                                   LearningScope(owner_id="student-1", course_id="other")])
async def test_private_quiz_read_and_start_cannot_cross_scope(scope):
    _, _, gen, quizzes, _, _ = composition()
    public = await gen.generate_quiz(SCOPE, context(), topic="topic", question_count=1, difficulty="easy")
    assert quizzes.quiz_for_student(public["quiz_id"], SCOPE) == public
    with pytest.raises(ValueError, match="learning_scope_forbidden"):
        quizzes.quiz_for_student(public["quiz_id"], scope)
    with pytest.raises(ValueError, match="learning_scope_forbidden|course_mismatch"):
        quizzes.start(StartAttemptRequest(quiz_id=public["quiz_id"], student_id=scope.owner_id, course_id=scope.course_id))


@pytest.mark.parametrize("scope", [LearningScope(owner_id="other", course_id="course-1"),
                                   LearningScope(owner_id="student-1", course_id="other")])
def test_flashcard_read_and_review_cannot_cross_scope(scope):
    state, repo = evidence_repo()
    repo.register_flashcard(FlashcardRegistration(flashcard_id="card", course_id="course-1", topic="topic",
        front_text="front", back_text="back", owner_id="student-1"))
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="learning_scope_forbidden"):
        repo.flashcard("card", scope)
    with pytest.raises(ValueError, match="learning_scope_forbidden"):
        repo.review("card", FlashcardReviewRequest(student_id=scope.owner_id, rating="GOOD", review_id="r"), scope=scope)
    assert state == before


@pytest.mark.asyncio
async def test_empty_progress_has_explicit_no_evidence_recommendation():
    _, repo = evidence_repo()
    assert repo.mastery_for("student-1", "course-1") == []
    snapshot = repo.mastery_for("student-1", "course-1", "topic")[0]
    provider = Mock(generate=AsyncMock())
    result = await RecommendationService(provider).get_recommendations(snapshot, ["topic"])
    assert result["mastery_score"] is None
    assert result["level"] == "INSUFFICIENT_EVIDENCE"
    provider.generate.assert_not_awaited()


def test_persisted_quiz_requires_unique_ids_and_bounded_content():
    _, repo = state_repo()
    duplicate = copy.deepcopy(QUESTIONS[0])
    duplicate["question"] = "Different question"
    with pytest.raises(ValueError, match="invalid_quiz_definition"):
        repo.save_quiz(QuizDefinitionRequest(quiz_id="q", course_id="course-1", topic="topic", difficulty="easy", questions=[QUESTIONS[0], duplicate]))
    oversized = copy.deepcopy(QUESTIONS[0])
    oversized["question"] = "x" * 8001
    with pytest.raises(ValueError, match="invalid_quiz_definition"):
        repo.save_quiz(QuizDefinitionRequest(quiz_id="q", course_id="course-1", topic="topic", difficulty="easy", questions=[oversized]))


def test_internal_validation_errors_never_expose_stored_data():
    repository = Mock()
    repository.quiz_for_student.side_effect = ValueError("SECRET_STORED_CONTEXT")
    app = FastAPI()
    app.include_router(create_quiz_router(repository, scope_dependency=lambda: SCOPE))
    response = TestClient(app).get("/quizzes/q")
    assert response.status_code == 422
    assert "SECRET" not in response.text
