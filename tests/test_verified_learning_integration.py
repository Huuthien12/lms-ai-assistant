import sys
import logging
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
from verified_learning_router import create_verified_learning_router, question_citations
from verified_identity_router import create_identity_router
from course_query_auth import create_moodle_query_authorizer
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.contracts import AuthorizedCourseScope
from test_verified_chat_integration import runtime, document
from verified_learning_fakes import LearningConnection


def quiz_events(caplog):
    prefix="quiz_observability "
    return [json.loads(record.getMessage()[len(prefix):]) for record in caplog.records
            if record.getMessage().startswith(prefix)]


def flashcard_events(caplog):
    prefix="flashcard_observability "
    return [json.loads(record.getMessage()[len(prefix):]) for record in caplog.records
            if record.getMessage().startswith(prefix)]


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
            questions=[]
            for i,candidate in enumerate(payload["quiz_candidates"][:count]):
                answer=candidate["text"]
                questions.append({
                    "question":f"Nội dung nào được nêu trong tài liệu đã xác minh ở ý {i + 1}?","type":"mcq",
                    "options":[{"id":"A","text":answer},{"id":"B","text":f"distractor {i}b"},
                               {"id":"C","text":f"distractor {i}c"},{"id":"D","text":f"distractor {i}d"}],
                    "correct_option_id":"A","explanation":"Copied from verified context.",
                    "evidence_id":candidate["evidence_id"],"answer_span_id":candidate["answer_span_id"]})
            content=json.dumps({"questions":questions})
        elif "flashcards" in system:
            request=json.loads(kwargs["prompt"]); count=request["count"]
            cards=([{"front_text":"Python?","back_text":"Language","topic":"model topic","difficulty":"hard"}]
                   if count==1 else [{"front_text":f"Python {request['topic']} {i}","back_text":"Verified Python lessons","topic":"model topic","difficulty":"medium"} for i in range(count)])
            content=json.dumps({"flashcards":cards})
        elif "already-known grading result" in system:
            content=json.dumps({"explanation":"Python is a language.","key_concept":"Programming"})
        else: content="Grounded answer"
        return LLMResult("success","fake","fake",content,0)
    orch.generate=AsyncMock(side_effect=generate)
    app=FastAPI(); app.include_router(create_identity_router(auth)); app.include_router(create_verified_learning_router(auth,pub,store,orch,GroundedChatService(orch),RecommendationService(orch)))
    return TestClient(app),store,state,orch,pub,adapter


def headers(user="A"): return {"Authorization":"Bearer "+user}
def generation(): return {"question":"Explain Python","topic":"Python","count":1,"difficulty":"easy"}


def test_question_citations_use_only_the_question_source_id():
    citations=[
        {"source_id":"course-a/chunk-1","document_id":"doc-a","title":"A.pdf"},
        {"source_id":"course-a/chunk-2","document_id":"doc-a","title":"A.pdf"},
        {"source_id":"course-a/chunk-3","document_id":"doc-b","title":"B.pdf"},
        {"source_id":"other-course/chunk-1","document_id":"doc-other","title":"Other.pdf"},
    ]
    question={"source_metadata":[{"source_id":"course-a/chunk-1"},{"source_id":"course-a/chunk-2"}]}
    assert question_citations(question,citations) == citations[:2]
    assert question_citations({},citations) == []


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


def test_post_quiz_review_flashcards_uses_server_wrong_answers_and_is_idempotent(learning):
    client,_,state,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    created=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert created.status_code==200,created.text
    body=created.json(); assert body["status"]=="READY" and body["flashcards"]
    assert "correct_option_id" not in created.text and state["cards"]
    again=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert again.json()=={"attempt_id":attempt,"batch_id":body["batch_id"],"status":"READY","flashcards":[]}


def test_post_quiz_review_flashcards_all_correct_skips_provider(learning):
    client,_,_,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"A"}]})
    orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.json()=={"attempt_id":attempt,"status":"NO_REVIEW_NEEDED","flashcards":[]}
    orch.generate.assert_not_awaited()


def test_post_quiz_review_flashcards_denies_foreign_owner_and_unsubmitted_attempt(learning):
    client,_,_,_,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    assert client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers("B")).status_code==403
    pending=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert pending.status_code==409 and pending.json()["detail"]["code"]=="attempt_not_submitted"


def test_post_quiz_review_flashcards_rechecks_revoked_course_access(learning):
    client,_,_,orch,_,adapter=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    adapter.authorization_state["revoked"]=True; orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==403 and response.json()["detail"]["code"]=="course_access_denied"
    orch.generate.assert_not_awaited()


@pytest.mark.parametrize("mutation",["legacy","ambiguous"])
def test_post_quiz_review_flashcards_rejects_untrusted_provenance(learning,mutation):
    client,_,state,_,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    definition=list(state["definitions"][quiz["quiz_id"]]); questions=json.loads(definition[3])
    if mutation=="legacy": questions[0].pop("trusted_provenance",None)
    else: questions[0]["trusted_provenance"]["bindings"].append({**questions[0]["trusted_provenance"]["bindings"][0],"chapter_id":"other-chapter"})
    definition[3]=json.dumps(questions); state["definitions"][quiz["quiz_id"]]=tuple(definition)
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==409 and response.json()["detail"]=={"code":"trusted_topic_mapping_unavailable","message":"Review material is unavailable."}


def test_post_quiz_review_flashcards_provider_failure_keeps_batch_unpublished(learning):
    client,_,state,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    orch.generate.side_effect=lambda **_: LLMResult("error","fake","fake","",0,error_code="HTTP_500")
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==502 and response.json()["detail"]["code"]=="FLASHCARD_GENERATION_FAILED" and not state["cards"]
    assert state["batches"] and next(iter(state["batches"].values()))[3]=="FAILED"


def test_post_quiz_review_flashcards_rejects_deleted_active_source(learning):
    client,_,_,orch,pub,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    record=next(iter(pub.ledger.snapshot().records.values()))
    from deeptutor_integration.contracts import AuthorizedCourseScope
    scope=AuthorizedCourseScope(record.moodle_course_id,record.course_id,record.kb_id,"owner",record.source_namespace)
    pub.delete(scope,"1"); orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==422 and response.json()["detail"]=={"code":"invalid_chapter","message":"The selected chapter is not an active publication."}
    assert not orch.generate.await_count


def test_post_quiz_review_flashcards_rejects_stale_source_binding(learning):
    client,_,state,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    definition=list(state["definitions"][quiz["quiz_id"]]); questions=json.loads(definition[3])
    questions[0]["trusted_provenance"]["bindings"][0]["version"]="retired-version"
    definition[3]=json.dumps(questions); state["definitions"][quiz["quiz_id"]]=tuple(definition)
    orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==409 and response.json()["detail"]=={"code":"trusted_topic_mapping_unavailable","message":"Learning request could not be completed."}
    orch.generate.assert_not_awaited()


def test_post_quiz_review_flashcards_groups_distinct_trusted_chapters(learning):
    client,_,state,_,pub,_=learning
    pub.publish(AuthorizedCourseScope(9,"INT1339","int1339-python","owner","https://moodle.test"),
                document("Verified Java lessons cover classes interfaces modules.").model_copy(update={"document_id":"2","original_filename":"chapter-two.md"}))
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json={**generation(),"count":2}).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    answers=[{"question_id":question["question_id"],"selected_option_id":"B"} for question in quiz["questions"]]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":answers})
    chapter_one=next(record for record in pub.ledger.snapshot().records.values() if record.document_id=="1")
    chapter_two=next(record for record in pub.ledger.snapshot().records.values() if record.document_id=="2")
    definition=list(state["definitions"][quiz["quiz_id"]]); questions=json.loads(definition[3])
    questions[0]["trusted_provenance"]={"version":1,"bindings":[{"source_id":chapter_one.chunk_manifest[0].source_ref,
        "chapter_id":"1","version":chapter_one.document_version_id,"content_hash":chapter_one.chunk_manifest[0].content_sha256}]}
    questions[1]["trusted_provenance"]={"version":1,"bindings":[{"source_id":chapter_two.chunk_manifest[0].source_ref,
        "chapter_id":"2","version":chapter_two.document_version_id,"content_hash":chapter_two.chunk_manifest[0].content_sha256}]}
    definition[3]=json.dumps(questions); state["definitions"][quiz["quiz_id"]]=tuple(definition)
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.status_code==200,response.text
    body=response.json(); assert body["status"]=="READY" and len(body["flashcards"])==10
    assert {row[2] for row in state["batch_cards"]}=={"1","2"}


def test_post_quiz_review_flashcards_reports_active_reservation_as_pending(learning):
    client,store,state,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":[{"question_id":quiz["questions"][0]["question_id"],"selected_option_id":"B"}]})
    row=state["attempts"][attempt]
    scope=AuthorizedCourseScope(9,"INT1339","int1339-python",row["student_id"],"https://moodle.test")
    reserved=store.reserve_review_batch(attempt,scope,{"chapters":["1"]})
    orch.generate.reset_mock()
    response=client.post(f"/learning/attempts/{attempt}/review-flashcards",headers=headers())
    assert response.json()=={"attempt_id":attempt,"batch_id":reserved["batch_id"],"status":"PENDING","flashcards":[]}
    orch.generate.assert_not_awaited()


def test_three_question_review_is_mapped_by_question_id(learning):
    client,_,_,orch,_,_=learning
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),
                         json={**generation(),"count":3})
    assert response.status_code==200, response.json().get("detail",{}).get("code")
    quiz=response.json()
    assert len(quiz["questions"])==3
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    answers=[{"question_id": question["question_id"], "selected_option_id": "A"}
             for question in quiz["questions"]]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":answers})
    review=client.get(f"/learning/attempts/{attempt}/review",headers=headers()).json()["results"]
    assert [item["question_id"] for item in review] == [item["question_id"] for item in answers]
    assert all(item["explanation_status"] == "available" for item in review)
    assert all(item["correct_answer"] for item in review)


def test_review_can_request_only_unavailable_question_without_reordering(learning):
    client,_,_,_,_,_=learning
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),
                         json={**generation(),"count":3})
    assert response.status_code==200, response.json().get("detail",{}).get("code")
    quiz=response.json()
    assert len(quiz["questions"])==3
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    answers=[{"question_id": question["question_id"], "selected_option_id": "A"}
             for question in quiz["questions"]]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),json={"answers":answers})
    requested=answers[1]["question_id"]
    review=client.get(f"/learning/attempts/{attempt}/review?question_id={requested}",headers=headers()).json()["results"]
    assert [item["question_id"] for item in review] == [requested]


def test_review_provider_failure_is_not_reported_as_publication_failure(learning):
    client,_,_,orch,_,_=learning
    quiz=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).json()
    attempt=client.post(f"/learning/quizzes/{quiz['quiz_id']}/attempts",headers=headers()).json()["attempt_id"]
    question_id=quiz["questions"][0]["question_id"]
    client.post(f"/learning/attempts/{attempt}/submit",headers=headers(),
                json={"answers":[{"question_id":question_id,"selected_option_id":"B"}]})
    orch.generate.side_effect=lambda **kwargs: LLMResult(
        "error","groq","model","",0,error_code="HTTP_429")
    review=client.get(f"/learning/attempts/{attempt}/review",headers=headers()).json()["results"]
    assert review[0]["explanation_status"] == "provider_rate_limited"


def test_flashcard_content_persists_and_review_evidence_is_idempotent(learning):
    client,store,state,orch,_,_=learning
    created=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation()).json()
    card=created["flashcards"][0]
    assert card["front_text"]=="Python?" and card["back_text"]=="Language" and card["topic"]=="Python"
    reloaded=client.get("/learning/courses/INT1339/flashcards",headers=headers()).json()["flashcards"]
    assert reloaded[0]["flashcard_id"]==card["flashcard_id"]
    assert reloaded[0]["reviewed"] is False and reloaded[0]["needs_review"] is True
    path=f"/learning/flashcards/{card['flashcard_id']}/reviews"
    assert client.post(path,headers=headers(),json={"rating":"GOOD","review_id":"once"}).status_code==200
    assert client.post(path,headers=headers(),json={"rating":"GOOD","review_id":"once"}).status_code==200
    assert len(state["events"])==1
    reviewed=client.get("/learning/courses/INT1339/flashcards",headers=headers()).json()["flashcards"][0]
    assert reviewed["reviewed"] is True and reviewed["needs_review"] is False
    assert reviewed["latest_rating"]=="GOOD"
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
def test_generation_can_select_only_an_active_chapter(learning,path):
    client,_,state,orch,pub,adapter=learning
    active=client.get("/learning/courses/INT1339/documents",headers=headers()).json()["publications"][0]
    adapter.retrieve.reset_mock()
    body={**generation(),"scope_mode":"chapter","chapter_id":active["document_id"]}
    response=client.post("/learning/courses/INT1339/"+path,headers=headers(),json=body)
    assert response.status_code==200
    assert adapter.retrieve.call_count==1
    before=deepcopy(state); orch.generate.reset_mock(); adapter.retrieve.reset_mock()
    denied=client.post("/learning/courses/INT1339/"+path,headers=headers(),json={
        **body,"chapter_id":"not-active"})
    assert denied.status_code==422 and denied.json()["detail"]["code"]=="invalid_chapter"
    assert state==before and adapter.retrieve.call_count==0
    orch.generate.assert_not_awaited()


def test_exact_saved_flashcard_duplicate_is_not_persisted_again(learning):
    client,_,state,_,_,_=learning
    first=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation())
    assert first.status_code==200 and len(state["cards"])==1
    before=deepcopy(state)
    second=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation())
    assert second.status_code==409 and second.json()["detail"]["code"]=="NO_NEW_FLASHCARDS"
    assert state==before


def test_malformed_provider_output_creates_no_trusted_artifact(learning):
    client,_,state,orch,_,_=learning
    orch.generate.side_effect=None; orch.generate.return_value=LLMResult("success","fake","fake","INVALID JSON",0)
    assert client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).status_code==502
    assert not state["definitions"] and not state["bindings"]


def test_grounding_rejection_is_422_with_safe_counts_and_no_persistence(learning):
    client,_,state,orch,_,_=learning
    async def unsupported_span(**kwargs):
        payload=json.loads(kwargs["prompt"])
        return LLMResult("success","fake","fake",json.dumps({"questions":[{
            "question":"Nội dung nào được nêu trong tài liệu?","type":"mcq",
            "evidence_id":payload["verified_evidence"][0]["evidence_id"],"answer_span_id":"not-a-span",
            "options":[{"id":"A","text":"unsupported"},{"id":"B","text":"one"},
                       {"id":"C","text":"two"},{"id":"D","text":"three"}],
            "correct_option_id":"A","explanation":"Không được xác minh.",
        }]}),0)
    orch.generate.side_effect=unsupported_span
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==422
    assert response.json()["detail"] == {"code":"QUIZ_GROUNDING_FAILED",
        "message":"Learning request could not be completed.","requested_count":1,"validated_count":0}
    assert not state["definitions"] and not state["bindings"]


def test_provider_timeout_returns_504_without_persistence(learning,caplog):
    client,_,state,orch,_,_=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    before=deepcopy(state); orch.generate.side_effect=None
    orch.generate.return_value=LLMResult(
        "error","ollama","qwen2.5:3b","SECRET_PROVIDER_BODY",30000,
        error_code="TIMEOUT_OR_NETWORK_ERROR")
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==504
    assert response.json()["detail"]=={
        "code":"LEARNING_GENERATION_TIMEOUT",
        "message":"Learning request could not be completed."}
    assert state==before
    events=quiz_events(caplog)
    assert {(event["stage"],event["result"]) for event in events}>={
        ("authorization_pre_generation","passed"),("retrieval_context","passed"),
        ("provider","started"),("provider","failed"),
        ("structural_validation","not_reached"),
        ("semantic_validation","not_reached"),("persistence","not_reached")}
    assert len({event["correlation_id"] for event in events})==1
    assert not any(stage.startswith("artifact_persistence") for stage in
                   (event["stage"] for event in events))
    assert "SECRET_PROVIDER_BODY" not in caplog.text
    assert "trusted full lecture context" not in caplog.text
    assert all(event["elapsed_ms"]>=0 for event in events)
    orch.generate.assert_awaited_once()


def test_provider_rate_limit_returns_429_without_retry_or_persistence(learning):
    client,_,state,orch,_,_=learning
    before=deepcopy(state); orch.generate.side_effect=None
    orch.generate.return_value=LLMResult(
        "error","groq","qwen/qwen3.8-27b","",10,error_code="HTTP_429",
        metadata={"provider_http_status":429,"retry_after_seconds":30})
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==429
    assert response.json()["detail"]["code"]=="LEARNING_RATE_LIMITED"
    assert state==before
    orch.generate.assert_awaited_once()


def test_retrieval_timeout_returns_504_before_provider_or_persistence(learning,caplog):
    client,_,state,orch,_,adapter=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    before=deepcopy(state); orch.generate.reset_mock()
    adapter.retrieve.side_effect=DeepTutorError(
        "retrieval_timeout","Verified retrieval timed out.",status_code=504)
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==504
    assert response.json()["detail"]["code"]=="retrieval_timeout"
    assert state==before
    orch.generate.assert_not_awaited()
    assert ("retrieval_context","failed") in {
        (event["stage"],event["result"]) for event in quiz_events(caplog)}


def test_flashcard_sql_failure_rolls_back_and_stops_loading(learning,caplog):
    client,store,state,orch,_,_=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    store.evidence.register_flashcards=MagicMock(side_effect=ValueError("persistence_failure"))
    response=client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation())
    assert response.status_code==503
    assert response.json()["detail"]["code"]=="persistence_failure"
    assert not state["cards"] and not state["bindings"]
    assert [(event["stage"],event["result"]) for event in flashcard_events(caplog)][-3:]==[
        ("persistence","started"),("persistence","failed"),("response","failed")]
    orch.generate.assert_awaited_once()


def test_success_observability_reaches_persistence_without_private_content(learning,caplog):
    client,_,state,orch,_,_=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==200 and len(state["definitions"])==1
    events=quiz_events(caplog)
    assert [(event["stage"],event["result"]) for event in events]==[
        ("authorization_pre_generation","passed"),("retrieval_context","passed"),
        ("provider","started"),("provider","passed"),
        ("structural_validation","started"),("structural_validation","passed"),
        ("semantic_validation","passed"),("persistence","started"),
        ("persistence","passed"),("artifact_persistence","started"),
        ("artifact_persistence","passed"),("response","passed")]
    assert len({event["correlation_id"] for event in events})==1
    assert "trusted full lecture context" not in caplog.text
    assert "correct_option_id" not in caplog.text
    orch.generate.assert_awaited_once()


def test_quiz_persistence_failure_is_sanitized_and_observable(learning,caplog):
    client,store,state,orch,_,_=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    store.quizzes.save_quiz=MagicMock(side_effect=ValueError("persistence_failure"))
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==503
    assert response.json()["detail"]=={
        "code":"persistence_failure","message":"Learning request could not be completed."}
    assert [(event["stage"],event["result"]) for event in quiz_events(caplog)][-3:]==[
        ("persistence","started"),("persistence","failed"),("response","failed")]
    assert not state["definitions"] and not state["bindings"]
    assert "trusted full lecture context" not in caplog.text
    assert "correct_option_id" not in caplog.text
    orch.generate.assert_awaited_once()


def test_artifact_persistence_failure_is_sanitized_and_observable(learning,caplog):
    client,store,state,orch,_,_=learning
    caplog.set_level(logging.INFO,logger="uvicorn.error")
    store.put=MagicMock(side_effect=ValueError("persistence_failure"))
    response=client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation())
    assert response.status_code==503
    assert response.json()["detail"]=={
        "code":"persistence_failure","message":"Learning request could not be completed."}
    events=[(event["stage"],event["result"]) for event in quiz_events(caplog)]
    assert events[-5:]==[("persistence","started"),("persistence","passed"),
                        ("artifact_persistence","started"),("artifact_persistence","failed"),
                        ("response","failed")]
    assert len(state["definitions"])==1 and not state["bindings"]
    assert "trusted full lecture context" not in caplog.text
    assert "correct_option_id" not in caplog.text
    orch.generate.assert_awaited_once()


@pytest.mark.parametrize("path",["quizzes","flashcards"])
def test_learning_update_delete_never_sends_old_context_to_provider(learning,path):
    client,store,_,orch,pub,_=learning
    scope=next(iter(pub.ledger.snapshot().records.values()))
    from deeptutor_integration.contracts import AuthorizedCourseScope
    authorized=AuthorizedCourseScope(scope.moodle_course_id,scope.course_id,scope.kb_id,"owner",scope.source_namespace)
    pub.publish(authorized,document(
        "NEW_VERSION_ONLY establishes the sole active verified context for this test."))
    orch.generate.reset_mock()
    response=client.post("/learning/courses/INT1339/"+path,headers=headers(),json=generation())
    assert response.status_code==200, response.json().get("detail",{}).get("code")
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
