"""Opt-in real SQL acceptance; Moodle/SDK/provider transports remain deterministic fakes.

LMS_ACCEPTANCE_ENV_FILE points to local SQL configuration. Only newly created,
uniquely named test databases are touched and removed. Run this file explicitly.
"""
import ast
import json
import os
import re
import sys
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pyodbc
import pytest
from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.testclient import TestClient

pyodbc.pooling = False
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "lms-dlu-demo")]
from test_final_team_integration import team, learning, runtime, sync, headers, generation
from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.recommendation_service import RecommendationService
from backend.services.ai.grading_service import GradingService
from backend.services.ai.learning_context import LearningScope
from quiz_lifecycle import QuizRepository, StartAttemptRequest, create_quiz_router
from learning_evidence import LearningEvidenceRepository, FlashcardRegistration, create_learning_router
from verified_learning_repository import VerifiedLearningRepository, restore_context
from verified_learning_router import create_verified_learning_router
from legacy_route_security import create_learning_scope_dependency, resource_owner_lookup, install_legacy_security


def legacy_schema(repository):
    method = next(node for node in ast.walk(ast.parse(Path(sys.modules[repository.__module__].__file__).read_text(encoding="utf-8")))
                  if isinstance(node, ast.FunctionDef) and node.name == "ensure_schema")
    sql = next(node.value for node in ast.walk(method) if isinstance(node, ast.Constant) and isinstance(node.value, str) and "CREATE TABLE" in node.value)
    return re.sub(r"IF COL_LENGTH\([^;]+?;", "", sql, flags=re.S)


@pytest.fixture(params=["empty", "populated_legacy"])
def sql_store(request):
    config = {**dotenv_values(os.getenv("LMS_ACCEPTANCE_ENV_FILE", str(ROOT / ".env"))), **os.environ}
    driver = config.get("LMS_DB_DRIVER") or "ODBC Driver 17 for SQL Server"
    server = config.get("LMS_DB_SERVER") or "localhost"
    # This acceptance target uses local Windows integrated authentication only.
    template = f"DRIVER={{{driver}}};SERVER={server};DATABASE={{database}};Trusted_Connection=yes;TrustServerCertificate=yes;Connection Timeout=5;"
    name = "codex_acceptance_" + uuid.uuid4().hex
    assert re.fullmatch(r"codex_acceptance_[0-9a-f]{32}", name)
    master = pyodbc.connect(template.replace("{database}","master"), autocommit=True)
    connections = []
    created = False
    def connect():
        connection = pyodbc.connect(template.replace("{database}",name))
        connections.append(connection)
        return connection
    def scalar(sql, *args):
        with connect() as connection:
            return connection.cursor().execute(sql, *args).fetchone()[0]
    try:
        assert master.cursor().execute("SELECT DB_ID(?)", name).fetchone()[0] is None
        master.execute(f"CREATE DATABASE [{name}]")
        created = True
        if request.param == "populated_legacy":
            with connect() as connection:
                cursor = connection.cursor()
                cursor.execute(legacy_schema(LearningEvidenceRepository))
                cursor.execute(legacy_schema(QuizRepository))
                cursor.execute("INSERT INTO dbo.QuizDefinitions (quiz_id,course_id,topic,difficulty,questions_json,created_at) VALUES ('legacy','INT1339','Python','easy','[]',SYSUTCDATETIME())")
                cursor.execute("INSERT INTO dbo.Flashcards (flashcard_id,course_id,topic,created_at) VALUES ('legacy','INT1339','Python',SYSUTCDATETIME())")
                connection.commit()
        evidence = LearningEvidenceRepository(connect)
        quizzes = QuizRepository(connect, evidence)
        store = VerifiedLearningRepository(connect, quizzes, evidence)
        for _ in range(3):
            evidence.ensure_schema(); quizzes.ensure_schema(); store.ensure_schema()
        if request.param == "populated_legacy":
            assert scalar("SELECT COUNT(*) FROM dbo.QuizDefinitions WHERE quiz_id='legacy' AND context_json IS NULL") == 1
            assert scalar("SELECT COUNT(*) FROM dbo.Flashcards WHERE flashcard_id='legacy' AND artifact_json IS NULL") == 1
            assert quizzes.quiz("legacy")["learning_context"] is None
            with pytest.raises(ValueError, match="flashcard_context_unavailable"):
                evidence.flashcard("legacy", LearningScope(owner_id="A", course_id="INT1339"))
        yield store, scalar, request.param
    finally:
        for connection in connections:
            connection.close()
        if created:
            assert re.fullmatch(r"codex_acceptance_[0-9a-f]{32}", name)
            master.execute(f"DROP DATABASE [{name}]")
            assert master.cursor().execute("SELECT DB_ID(?)", name).fetchone()[0] is None
            print("OWNED_SQL_TEST_DATABASE_REMOVED; PRODUCTION_DATABASE_MODIFIED=False")
        master.close()


def test_final_team_sql_acceptance(team, sql_store):
    _,_,_,orch,pub,_,_,auth = team
    store, scalar, mode = sql_store
    app = FastAPI()
    app.include_router(create_verified_learning_router(auth,pub,store,orch,GroundedChatService(orch),RecommendationService(orch)))
    lookup=resource_owner_lookup(store.connect)
    scope_dependency=create_learning_scope_dependency(auth,lookup)
    app.include_router(create_quiz_router(store.quizzes,scope_dependency=scope_dependency))
    app.include_router(create_learning_router(store.evidence,scope_dependency=scope_dependency))
    install_legacy_security(app,auth,lookup)
    with TestClient(app) as client:
        assert sync(client).status_code == 200
        quiz_response = client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
        assert quiz_response.status_code == 200, quiz_response.text
        public = quiz_response.json()
        encoded = json.dumps(public)
        for forbidden in ("correct_option_id", "explanation", "context_json", "TAIL_AFTER_200"):
            assert forbidden not in encoded
        quiz_id, question_id = public["quiz_id"], public["questions"][0]["question_id"]
        trusted = store.quizzes.quiz(quiz_id)
        context = trusted["learning_context"]
        assert context and "TAIL_AFTER_200" in context.text and context.sources[0].provenance_status == "verified"
        binding = restore_context(store.get("quiz",quiz_id)["payload"]["context"])
        assert pub.learning_context(binding) == context
        scope = context.scope
        assert client.get("/learning/quizzes/"+quiz_id,headers=headers()).json() == public
        assert client.get("/quizzes/"+quiz_id,headers=headers()).status_code == 200
        assert client.get("/quizzes/"+quiz_id,headers=headers("B")).status_code == 403
        for other in (LearningScope(owner_id="foreign",course_id=scope.course_id),LearningScope(owner_id=scope.owner_id,course_id="OTHER")):
            with pytest.raises(ValueError,match="learning_scope_forbidden"):
                store.quizzes.quiz_for_student(quiz_id,other)
        with ThreadPoolExecutor(max_workers=2) as pool:
            attempts=list(pool.map(lambda _:store.quizzes.start(StartAttemptRequest(student_id=scope.owner_id,course_id=scope.course_id,quiz_id=quiz_id)),range(2)))
        attempt=attempts[0]["attempt_id"]
        assert attempt == attempts[1]["attempt_id"]
        orch.generate.reset_mock()
        invalid=client.post("/learning/attempts/"+attempt+"/submit",headers=headers(),json={"answers":[{"question_id":"foreign","selected_option_id":"A"}]})
        assert invalid.status_code == 422 and scalar("SELECT COUNT(*) FROM dbo.QuizAnswers") == 0
        assert client.post("/learning/attempts/"+attempt+"/submit",headers=headers("B"),json={"answers":[]}).status_code == 403
        submission={"answers":[{"question_id":question_id,"selected_option_id":"A"}]}
        assert client.post("/learning/attempts/"+attempt+"/submit",headers=headers(),json=submission).json()["score_percent"] == 100
        orch.generate.assert_not_awaited()
        assert client.get("/learning/attempts/"+attempt+"/review",headers=headers()).json()["results"][0]["explanation_status"] == "available"
        assert "TAIL_AFTER_200" in orch.generate.call_args.kwargs["prompt"]
        assert scalar("SELECT correct FROM dbo.QuizAnswers WHERE attempt_id=?",attempt) == 1
        assert scalar("SELECT COUNT(*) FROM dbo.LearningEvents") == 1
        assert store.evidence.mastery_for(scope.owner_id,scope.course_id)[0]["mastery_score"] == 100
        assert client.post("/learning/attempts/"+attempt+"/submit",headers=headers(),json=submission).status_code == 409
        assert store.evidence.mastery_for("foreign",scope.course_id) == []
        assert store.evidence.mastery_for(scope.owner_id,"OTHER") == []
        no_evidence=store.evidence.mastery_for(scope.owner_id,scope.course_id,"no evidence")[0]
        assert no_evidence["mastery_score"] is None and no_evidence["evidence_count"] == 0
        cards=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation()).json()["flashcards"]
        card=cards[0]
        assert client.get("/learning/courses/INT1339/flashcards",headers=headers()).json()["flashcards"] == cards
        stored=store.evidence.flashcard(card["flashcard_id"],scope)
        assert stored["front_text"] == card["front_text"] and stored["back_text"] == card["back_text"]
        assert "TAIL_AFTER_200" in stored["learning_context"]["text"]
        assert client.get("/flashcards/"+card["flashcard_id"],headers=headers()).status_code == 200
        assert client.get("/flashcards/"+card["flashcard_id"],headers=headers("B")).status_code == 403
        new_card=FlashcardRegistration.model_validate(stored).model_copy(update={"flashcard_id":"rollback-card"})
        conflicting_card=FlashcardRegistration.model_validate(stored).model_copy(update={"front_text":"different content"})
        with pytest.raises(ValueError,match="flashcard_conflict"):
            store.evidence.register_flashcards([new_card,conflicting_card])
        assert scalar("SELECT COUNT(*) FROM dbo.Flashcards WHERE flashcard_id='rollback-card'") == 0
        with pytest.raises(ValueError,match="learning_scope_forbidden"):
            store.evidence.flashcard(card["flashcard_id"],LearningScope(owner_id="foreign",course_id=scope.course_id))
        path="/learning/flashcards/"+card["flashcard_id"]+"/reviews"
        with ThreadPoolExecutor(max_workers=2) as pool:
            reviews=list(pool.map(lambda _:client.post(path,headers=headers(),json={"rating":"GOOD","review_id":"once"}),range(2)))
        assert all(result.status_code == 200 for result in reviews)
        assert scalar("SELECT COUNT(*) FROM dbo.FlashcardReviews") == 1 and scalar("SELECT COUNT(*) FROM dbo.LearningEvents") == 2
        assert client.post(path,headers=headers(),json={"rating":"EASY","review_id":"once"}).status_code == 409
        class FailingEvidence(LearningEvidenceRepository):
            def record_quiz(self,cursor,**kwargs):
                super().record_quiz(cursor,**kwargs)
                raise RuntimeError("injected acceptance failure")
        repository=QuizRepository(store.connect,FailingEvidence(store.connect))
        rollback_attempt=repository.start(StartAttemptRequest(student_id=scope.owner_id,course_id=scope.course_id,quiz_id=quiz_id))["attempt_id"]
        with pytest.raises(ValueError,match="persistence_failure"):
            repository.submit(rollback_attempt,submission["answers"],GradingService(),scope=scope)
        assert scalar("SELECT COUNT(*) FROM dbo.QuizAnswers WHERE attempt_id=?",rollback_attempt) == 0
        assert scalar("SELECT status FROM dbo.QuizAttempts WHERE attempt_id=?",rollback_attempt) == "IN_PROGRESS"
        assert scalar("SELECT COUNT(*) FROM dbo.LearningEvents") == 2
        assert scalar("SELECT evidence_count FROM dbo.TopicMastery WHERE student_id=? AND course_id=?",scope.owner_id,scope.course_id) == 2
        assert client.get("/learning/courses/INT1339/progress",headers=headers()).status_code == 200
        print(json.dumps({"SQL_E2E":"PASS","mode":mode,"cases":["A_empty_schema","B_populated_migration","C_schema_idempotency","D_verified_quiz_context","E_full_flashcards","F_owner_course_isolation","G_deterministic_atomic_grade","H_duplicate_concurrent_requests","I_rollback_evidence_mastery"],"external_transports":"FAKE","LIVE_E2E":"NOT_VERIFIED"}))
