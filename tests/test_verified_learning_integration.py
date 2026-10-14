import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"lms-dlu-demo"))
from copy import deepcopy
import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.recommendation_service import RecommendationService
from quiz_lifecycle import QuizRepository
from learning_evidence import LearningEvidenceRepository
from verified_learning_repository import VerifiedLearningRepository, restore_context
from verified_learning_router import create_verified_learning_router
from verified_identity_router import create_identity_router
from course_query_auth import create_moodle_query_authorizer
from deeptutor_integration.service import DeepTutorService
from test_verified_chat_integration import runtime, document
from verified_learning_fakes import LearningConnection


@pytest.fixture
def learning(runtime):
    _,pub,scope,adapter,_,_=runtime; pub.publish(scope,document("trusted full lecture context "*30))
    state={"definitions":{},"attempts":{},"answers":{},"cards":{},"reviews":{},"events":[],"mastery":{},"bindings":{}}
    connect=lambda:LearningConnection(state)
    evidence=LearningEvidenceRepository(connect)
    quiz=QuizRepository(connect,evidence)
    store=VerifiedLearningRepository(connect,quiz,evidence)
    service=DeepTutorService(pub.config,MagicMock())
    auth=create_moodle_query_authorizer(service,"https://moodle.test")
    orch=MagicMock()
    async def generate(**kwargs):
        system=kwargs["system_prompt"]
        if "MCQ" in system:
            count=json.loads(kwargs["prompt"])["question_count"]
            content=json.dumps({"questions":[{"question":f"Python {i}?","type":"mcq","options":[{"id":"A","text":"Language"},{"id":"B","text":"Database"}],"correct_option_id":"A","explanation":"Language."} for i in range(count)]})
        elif "flashcards" in system:
            content=json.dumps({"flashcards":[{"front_text":"Python?","back_text":"Language","topic":"model topic","difficulty":"hard"}]})
        elif "already-known grading result" in system:
            content=json.dumps({"explanation":"Python is a language.","key_concept":"Programming"})
        else: content="Grounded answer"
        return LLMResult("success","fake","fake",content,0)
    orch.generate=AsyncMock(side_effect=generate)
    app=FastAPI(); app.include_router(create_identity_router(auth)); app.include_router(create_verified_learning_router(auth,pub,store,orch,GroundedChatService(orch),RecommendationService(orch)))
    return TestClient(app),store,state,orch,pub,adapter


def headers(user="A"): return {"Authorization":"Bearer "+user}
def generation(): return {"question":"Explain Python","topic":"Python","count":1,"difficulty":"easy"}


def test_chat_quiz_grade_evidence_progress_and_explanation_vertical_flow(learning):
    client,store,state,orch,pub,_=learning
    reply=client.post("/learning/courses/INT1339/chat",headers=headers(),json={"question":"Python?"})
    assert reply.status_code==200 and reply.json()["sources"]
    history=client.get("/learning/courses/INT1339/history",headers=headers()).json()["history"]
    assert history[0]["response"]["sources"]==reply.json()["sources"]
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    assert "correct_option_id" not in json.dumps(quiz) and "answer_key" not in json.dumps(quiz)
    quiz_id=quiz["quiz_id"]
    reloaded=client.get("/learning/quizzes/"+quiz_id,headers=headers()).json()
    assert reloaded==quiz
    attempt=client.post(f"/learning/quizzes/{quiz_id}/attempts",headers=headers()).json()["attempt_id"]
    orch.generate.reset_mock()
    question_id=quiz["questions"][0]["question_id"]
    spoof=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":question_id,"selected_option_id":"B","correct_option_id":"B"}]})
    assert spoof.status_code==422
    score=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":question_id,"selected_option_id":"B"}]}).json()
    assert score["score_percent"]==0 and score["correct_count"]==0
    orch.generate.assert_not_awaited()
    assert len(state["events"])==1 and state["events"][0]["course_id"]=="INT1339"
    before=deepcopy(state["answers"])
    review=client.get(f"/learning/attempts/{attempt}/review",headers=headers()).json()
    assert review["results"][0]["explanation_status"]=="available" and state["answers"]==before
    progress=client.get("/learning/courses/INT1339/progress",headers=headers()).json()
    assert progress["topics"][0]["mastery_score"]==0 and progress["mastery_model"]=="heuristic/rule-based"
    assert progress["recommendations"][0]["recommended_actions"]
    events=deepcopy(state["events"])
    assert client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[]}).status_code==409
    assert state["events"]==events
    pub.delete(restore_context(store.get("quiz",quiz_id)["payload"]["context"]).scope,"1")
    orch.generate.reset_mock()
    assert client.get(f"/learning/attempts/{attempt}/review",headers=headers()).json()["results"][0]["explanation_status"]=="unavailable"
    orch.generate.assert_not_awaited()


def test_flashcard_content_persists_and_review_evidence_is_idempotent(learning):
    client,store,state,orch,_,_=learning
    created=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation()).json()
    card=created["flashcards"][0]
    assert card["front_text"]=="Python?" and card["back_text"]=="Language" and card["topic"]=="Python"
    reloaded=client.get("/learning/courses/INT1339/flashcards",headers=headers()).json()["flashcards"]
    assert reloaded==[card]
    path=f"/learning/flashcards/{card['flashcard_id']}/reviews"
    assert client.post(path,headers=headers(),json={"rating":"GOOD","review_id":"once"}).status_code==200
    assert client.post(path,headers=headers(),json={"rating":"GOOD","review_id":"once"}).status_code==200
    assert len(state["events"])==1
    progress=client.get("/learning/courses/INT1339/progress",headers=headers()).json()
    assert progress["topics"][0]["mastery_score"]==75
    before=deepcopy(state)
    assert client.post(path,headers=headers("B"),json={"rating":"EASY","review_id":"spoof"}).status_code==403
    assert state==before


@pytest.mark.parametrize("operation",["quiz","flashcard","chat"])
def test_course_b_cannot_generate_course_a_material(learning,operation):
    client,_,state,orch,_,adapter=learning
    path={"quiz":"quizzes","flashcard":"flashcards","chat":"chat"}[operation]
    body=generation() if operation!="chat" else {"question":"Python?"}
    adapter.retrieve.reset_mock(); orch.generate.reset_mock(); before=deepcopy(state)
    response=client.post("/learning/courses/INT1339/"+path,headers=headers("B"),json=body)
    assert response.status_code==403 and state==before
    adapter.retrieve.assert_not_called(); orch.generate.assert_not_awaited()


def test_foreign_attempt_owner_is_denied_before_grade_or_mutation(learning):
    client,_,state,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()["quiz_id"]
    attempt=client.post(f"/learning/quizzes/{quiz}/attempts",headers=headers()).json()["attempt_id"]
    before=deepcopy(state); orch.generate.reset_mock()
    assert client.post(f"/learning/attempts/{attempt}/submit",headers=headers("B"),json={"answers":[]}).status_code==403
    assert client.get(f"/learning/attempts/{attempt}/review",headers=headers("B")).status_code==403
    assert state==before; orch.generate.assert_not_awaited()


def test_client_identity_key_score_and_context_claims_are_rejected(learning):
    client,_,state,orch,_,adapter=learning
    adapter.retrieve.reset_mock(); orch.generate.reset_mock()
    assert client.post("/learning/courses/INT1339/quizzes",headers=headers(),json={**generation(),"student_id":"B","source_metadata":[]}).status_code==422
    adapter.retrieve.assert_not_called(); orch.generate.assert_not_awaited()
    assert not state["definitions"]


def test_malformed_provider_output_creates_no_trusted_artifact(learning):
    client,_,state,orch,_,_=learning
    orch.generate.side_effect=None; orch.generate.return_value=LLMResult("success","fake","fake","INVALID JSON",0)
    assert client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).status_code==502
    assert not state["definitions"] and not state["bindings"]


def test_provider_timeout_returns_502_without_persistence(learning):
    client,_,state,orch,_,_=learning
    before=deepcopy(state); orch.generate.side_effect=None
    orch.generate.return_value=LLMResult(
        "error","ollama","qwen2.5:3b","",30000,error_code="TIMEOUT_OR_NETWORK_ERROR")
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==502
    assert response.json()["detail"]["code"]=="QUIZ_GENERATION_FAILED"
    assert state==before


@pytest.mark.parametrize("path",["quizzes","flashcards"])
def test_learning_update_delete_never_sends_old_context_to_provider(learning,path):
    client,store,_,orch,pub,_=learning
    scope=next(iter(pub.ledger.snapshot().records.values()))
    from deeptutor_integration.contracts import AuthorizedCourseScope
    authorized=AuthorizedCourseScope(scope.moodle_course_id,scope.course_id,scope.kb_id,"owner",scope.source_namespace)
    pub.publish(authorized,document("NEW_VERSION_ONLY "*40))
    orch.generate.reset_mock()
    response=client.post("/learning/courses/INT1339/"+path,headers=headers(),json=generation())
    assert response.status_code==200
    prompt=orch.generate.call_args.kwargs["prompt"]
    assert "NEW_VERSION_ONLY" in prompt and "trusted full lecture context" not in prompt
    pub.delete(authorized,"1"); orch.generate.reset_mock()
    assert client.post("/learning/courses/INT1339/"+path,headers=headers(),json=generation()).status_code==409
    orch.generate.assert_not_awaited()


def test_owner_history_and_progress_are_never_taken_from_client(learning):
    client,_,_,_,_,_=learning
    client.post("/learning/courses/INT1339/chat",headers=headers(),json={"question":"Python?"})
    assert client.get("/learning/courses/INT1339/history",headers=headers("B")).status_code==403
    assert client.get("/learning/courses/OTHER/history",headers=headers("B")).json()["history"]==[]
    assert client.get("/learning/courses/OTHER/progress?student_id=A",headers=headers("B")).json()["topics"]==[]


def test_lecturer_sync_requires_actual_capability_before_discovery(learning,monkeypatch):
    client,_,_,_,_,engine=learning
    from deeptutor_integration.moodle_trust import MoodleTrustBoundary
    discovery=MagicMock()
    monkeypatch.setattr(MoodleTrustBoundary,"discover",discovery)
    before=engine.publish.call_count
    assert client.post("/learning/courses/INT1339/documents/1/sync",headers=headers()).status_code==503
    assert client.post("/learning/courses/INT1339/documents/1/sync",headers=headers("B")).status_code==403
    discovery.assert_not_called(); assert engine.publish.call_count==before
