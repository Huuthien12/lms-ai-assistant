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
from backend.services.ai.quiz_service import QuizService
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
    _,pub,scope,adapter,_,_=runtime
    pub.publish(scope,document(
        "Verified Python lessons cover syntax variables functions classes modules. "
        + "trusted full lecture context "*30))
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
            payload=json.loads(kwargs["prompt"]); count=payload["question_count"]
            context=" ".join(payload["retrieved_context"].split())
            tokens=context.split(); excerpt=" ".join(tokens[:min(16,len(tokens))])
            candidates=[token for token in tokens if excerpt.count(token)==1 and len(token)>1]
            questions=[]
            for i in range(count):
                if i<len(candidates): evidence,answer=excerpt,candidates[i]
                else:
                    evidence=tokens[i%len(tokens)]
                    answer=evidence[1:-1]
                cloze=evidence.replace(answer,QuizService.GROUNDING_BLANK,1)
                questions.append({
                    "question":QuizService.GROUNDING_QUESTION_PREFIX+cloze,"type":"mcq",
                    "options":[{"id":"A","text":answer},{"id":"B","text":f"distractor {i}"}],
                    "correct_option_id":"A","explanation":"Copied from verified context.",
                    "grounding_evidence":evidence})
            content=json.dumps({"questions":questions})
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


def test_p6_five_question_cardinality_score_and_mastery_match_historical_shape(learning):
    client,_,state,orch,_,_=learning
    request={**generation(),"count":5}
    public=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=request).json()
    encoded=json.dumps(public)
    assert len(public["questions"])==5
    assert all(field not in encoded for field in ("correct_option_id","correct_answer","answer_key","explanation"))
    attempt=client.post(f"/learning/quizzes/{public['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    answers=[{"question_id":question["question_id"],"selected_option_id":"A" if index<2 else "B"}
             for index,question in enumerate(public["questions"])]
    orch.generate.reset_mock()
    result=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":answers})
    assert result.status_code==200
    assert result.json()["score_percent"]==40 and result.json()["correct_count"]==2
    assert len(state["attempts"])==1
    persisted=[(question,selection,correct) for (stored_attempt,question),(selection,correct) in state["answers"].items()
               if stored_attempt==attempt]
    assert len(persisted)==5 and len({question for question,_,_ in persisted})==5
    assert sum(correct for _,_,correct in persisted)==2
    assert len(state["events"])==5
    evidence_scopes={(event["student_id"],event["course_id"]) for event in state["events"]}
    assert len(evidence_scopes)==1 and next(iter(evidence_scopes))[1]=="INT1339"
    mastery=client.get("/learning/courses/INT1339/progress",headers=headers()).json()["topics"][0]
    assert (mastery["mastery_score"],mastery["level"],mastery["confidence"],mastery["evidence_count"])==(40,"WEAK","MEDIUM",5)
    orch.generate.assert_not_awaited()
    before=deepcopy(state)
    retry=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":answers})
    assert retry.status_code==409 and retry.json()["detail"]["code"]=="already_submitted"
    assert state==before


def test_missing_answer_is_persisted_as_unanswered_and_unknown_extra_is_atomic(learning):
    client,_,state,orch,_,_=learning
    public=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json={**generation(),"count":2}).json()
    attempt=client.post(f"/learning/quizzes/{public['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    first=public["questions"][0]["question_id"]
    before=deepcopy(state); orch.generate.reset_mock()
    rejected=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[
        {"question_id":first,"selected_option_id":"A"},{"question_id":"foreign","selected_option_id":"A"}]})
    assert rejected.status_code==422 and state==before
    result=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[
        {"question_id":first,"selected_option_id":"A"}]}).json()
    assert result["total_questions"]==2 and result["correct_count"]==1 and result["score_percent"]==50
    assert len(result["results"])==2 and sum(item["selected_option_id"] is None for item in result["results"])==1
    orch.generate.assert_not_awaited()


@pytest.mark.parametrize("forged",[
    {"correct_answer":"A"},{"correct":True},{"score":100},{"explanation":"trust me"},
])
def test_submit_rejects_all_client_owned_grading_fields(learning,forged):
    client,_,state,orch,_,_=learning
    public=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{public['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    answer={"question_id":public["questions"][0]["question_id"],"selected_option_id":"A",**forged}
    before=deepcopy(state); orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[answer]})
    assert response.status_code==422 and state==before
    orch.generate.assert_not_awaited()


def test_review_before_submit_and_inactive_source_have_controlled_semantics(learning):
    client,store,state,orch,pub,_=learning
    public=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{public['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    assert client.get(f"/learning/attempts/{attempt}/review",headers=headers()).status_code==409
    saved=restore_context(store.get("quiz",public["quiz_id"])["payload"]["context"])
    pub.delete(saved.scope,"1")
    orch.generate.reset_mock()
    submitted=client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{
        "question_id":public["questions"][0]["question_id"],"selected_option_id":"B"}]})
    assert submitted.status_code==200 and submitted.json()["score_percent"]==0
    assert len(state["events"])==1
    review=client.get(f"/learning/attempts/{attempt}/review",headers=headers()).json()
    assert review["results"][0]["explanation_status"]=="unavailable"
    orch.generate.assert_not_awaited()


def test_malformed_persisted_binding_is_sanitized_and_never_reaches_grading(learning):
    client,_,state,orch,_,_=learning
    public=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    owner,course,_=state["bindings"][("quiz",public["quiz_id"])]
    state["bindings"][("quiz",public["quiz_id"])]=(owner,course,"PRIVATE_KEY_MATERIAL")
    orch.generate.reset_mock()
    response=client.get("/learning/quizzes/"+public["quiz_id"],headers=headers())
    assert response.status_code==503
    assert response.json()["detail"]["code"]=="learning_dependency_unavailable"
    assert "PRIVATE_KEY_MATERIAL" not in response.text
    assert not state["attempts"] and not state["answers"] and not state["events"]
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


@pytest.mark.parametrize("path",["quizzes","flashcards"])
def test_malformed_provider_output_creates_no_trusted_artifact(learning,path):
    client,_,state,orch,_,_=learning
    orch.generate.side_effect=None; orch.generate.return_value=LLMResult("success","fake","fake","INVALID JSON",0)
    assert client.post("/learning/courses/INT1339/"+path,headers=headers(),json=generation()).status_code==502
    assert not state["definitions"] and not state["cards"] and not state["bindings"]


@pytest.mark.parametrize("path,code",[("quizzes","QUIZ_GENERATION_FAILED"),("flashcards","FLASHCARD_GENERATION_FAILED")])
def test_provider_timeout_returns_502_without_persistence(learning,path,code):
    client,_,state,orch,_,_=learning
    before=deepcopy(state); orch.generate.side_effect=None
    orch.generate.return_value=LLMResult(
        "error","ollama","qwen2.5:3b","",30000,error_code="TIMEOUT_OR_NETWORK_ERROR")
    response=client.post("/learning/courses/INT1339/"+path,headers=headers(),json=generation())
    assert response.status_code==502
    assert response.json()["detail"]["code"]==code
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
