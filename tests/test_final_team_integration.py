"""One real team composition with fake external Moodle/engine/provider transports."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/"lms-dlu-demo"))
from copy import deepcopy
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
import pytest
from fastapi import FastAPI,Request
from fastapi.testclient import TestClient
from backend.services.ai.grounded_chat import GroundedChatService
from backend.services.ai.recommendation_service import RecommendationService
from backend.services.ai.learning_context import LearningScope
from backend.services.ai.quiz_service import QuizService
from backend.services.ai.flashcard_service import FlashcardService
from learning_generation import LearningGenerationService
from verified_learning_router import create_verified_learning_router
from verified_identity_router import create_identity_router
from course_query_auth import create_moodle_query_authorizer
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.moodle_trust import MoodleRest,MoodleCoreCapabilityEvidence,moodle_document_id
from test_verified_learning_integration import learning,runtime,generation,headers

BASE="https://moodle.test"
DOC=moodle_document_id(BASE,9,1)


def response(data=None,content=None):
    result=MagicMock(status_code=200,headers={"Content-Type":"text/markdown"})
    result.json.return_value=data
    if content is not None: result.iter_content.return_value=[content]
    return result


@pytest.fixture
def team(learning,monkeypatch):
    _,store,state,orch,pub,engine=learning
    moodle={"content":b"ORIGINAL Moodle lecture "+b"full "*100+b"TAIL_AFTER_200","filename":"lecture.md","version":1,
            "deleted":False,"scan_failed":False,"cap_down":False,"revoked":False,"calls":[],"downloads":0}
    def rest(url,**kwargs):
        assert url==BASE+"/webservice/rest/server.php" and kwargs["allow_redirects"] is False
        assert "params" not in kwargs
        data=kwargs["data"]; token=data["wstoken"]; function=data["wsfunction"]
        moodle["calls"].append(function)
        uid={"A":1,"B":2,"L":3,"cap-service":99}.get(token)
        if function=="core_webservice_get_site_info":
            return response({"userid":uid,"siteurl":BASE,"functions":[{"name":"core_enrol_get_users_courses"}]})
        if function=="core_enrol_get_users_courses":
            assert data["userid"]==uid
            if token=="A" and moodle["revoked"]: return response([])
            return response([{"id":10 if token=="B" else 9,"shortname":"OTHER" if token=="B" else "INT1339"}])
        if function=="core_enrol_get_enrolled_users_with_capability":
            assert token=="cap-service" and data["options[0][value]"]==1
            if moodle["cap_down"]: return response({"errorcode":"service_unavailable"})
            return response([{"courseid":data["coursecapabilities[0][courseid]"],"capability":"moodle/course:manageactivities","users":[{"id":3}]}])
        assert function=="mod_resource_get_resources_by_courses" and token=="L"
        if moodle["scan_failed"]: return response({"errorcode":"scan_failed"})
        if moodle["deleted"]: return response({"resources":[]})
        return response({"resources":[{"id":1,"course":9,"contentfiles":[{"filename":moodle["filename"],"mimetype":"text/markdown",
            "timemodified":moodle["version"],"filesize":len(moodle["content"]),
            "fileurl":BASE+"/webservice/pluginfile.php/3/mod_resource/content/1/"+moodle["filename"]}]}]})
    def download(url,**kwargs):
        assert kwargs["params"]=={"token":"L"} and kwargs["allow_redirects"] is False
        assert "token" not in url and kwargs["stream"] is True
        moodle["downloads"]+=1
        return response(content=moodle["content"])
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.post",rest)
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.get",download)
    service=DeepTutorService(pub.config,MagicMock())
    auth=create_moodle_query_authorizer(service,BASE,
        capability_evidence=MoodleCoreCapabilityEvidence(MoodleRest(BASE),"cap-service"),forbidden_tokens=("cap-service","operator-service"))
    app=FastAPI(); app.include_router(create_identity_router(auth)); app.include_router(create_verified_learning_router(auth,pub,store,orch,GroundedChatService(orch),RecommendationService(orch)))
    return TestClient(app),store,state,orch,pub,engine,moodle,auth


def sync(client): return client.post("/learning/courses/INT1339/sync",headers=headers("L"))
def chat(client): return client.post("/learning/courses/INT1339/chat",headers=headers(),json={"question":"Explain Python"})


def test_moodle_lifecycle_to_verified_prompts_and_tombstone(team):
    client,store,state,orch,pub,engine,moodle,_=team
    first=sync(client)
    assert first.status_code==200 and "CANDIDATE" in [s["kind"] for s in first.json()["signals"]]
    active=[r for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"]
    assert len(active)==1 and active[0].document_id==DOC and active[0].moodle_resource_id==1
    version=active[0].document_version_id; calls=engine.publish.call_count
    assert [s["kind"] for s in sync(client).json()["signals"]]==["UNCHANGED"]
    moodle["filename"]="renamed.md"; moodle["version"]=2
    assert [s["kind"] for s in sync(client).json()["signals"]]==["UNCHANGED"]
    assert engine.publish.call_count==calls
    assert chat(client).status_code==200 and "TAIL_AFTER_200" in orch.generate.call_args.kwargs["prompt"]
    moodle["content"]=b"UPDATED Moodle lecture"; moodle["version"]=3
    assert sync(client).status_code==200
    current=[r for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"]
    assert len(current)==1 and current[0].document_version_id!=version
    assert chat(client).status_code==200
    prompt=orch.generate.call_args.kwargs["prompt"]
    assert "UPDATED" in prompt and "ORIGINAL" not in prompt and "TAIL_AFTER_200" not in prompt
    engine.publish.side_effect=RuntimeError("private upstream error")
    moodle["content"]=b"FAILED CANDIDATE"; moodle["version"]=4
    failed=sync(client); assert failed.status_code==502 and "private" not in failed.text
    assert [r.document_version_id for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"]==[current[0].document_version_id]
    assert chat(client).status_code==200 and "FAILED CANDIDATE" not in orch.generate.call_args.kwargs["prompt"]
    moodle["scan_failed"]=True
    assert sync(client).status_code==503
    assert [r.document_version_id for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"]==[current[0].document_version_id]
    moodle["scan_failed"]=False; moodle["deleted"]=True
    deleted=sync(client); assert deleted.status_code==200 and deleted.json()["signals"][0]["kind"]=="TOMBSTONE"
    orch.generate.reset_mock(); engine.retrieve.reset_mock()
    assert chat(client).status_code==200
    assert client.post("/learning/courses/INT1339/quizzes",headers=headers(),json=generation()).status_code==409
    assert client.post("/learning/courses/INT1339/flashcards",headers=headers(),json=generation()).status_code==409
    orch.generate.assert_not_awaited(); engine.retrieve.assert_not_called()


def test_capability_and_integration_credentials_fail_before_privileged_io(team):
    client,_,_,orch,pub,engine,moodle,_=team
    for actor,status in (("A",403),("B",403),("cap-service",401),("operator-service",401)):
        before=len(moodle["calls"])
        result=client.get("/learning/courses/INT1339/resources",headers=headers(actor))
        assert result.status_code==status and moodle["downloads"]==0
        if actor in {"cap-service","operator-service"}: assert len(moodle["calls"])==before
    assert "mod_resource_get_resources_by_courses" not in moodle["calls"]
    moodle["cap_down"]=True
    assert client.get("/learning/courses/INT1339/resources",headers=headers("L")).status_code==503
    assert "mod_resource_get_resources_by_courses" not in moodle["calls"]
    orch.generate.assert_not_awaited(); engine.retrieve.assert_not_called()


@pytest.mark.parametrize("operation",["quizzes","flashcards"])
def test_actual_validator_rejects_revocation_before_persistence(team,operation):
    client,_,state,orch,_,_,moodle,_=team
    assert sync(client).status_code==200
    original=orch.generate.side_effect
    async def revoked(**kwargs):
        result=await original(**kwargs); moodle["revoked"]=True; return result
    orch.generate.side_effect=revoked
    before=deepcopy(state)
    result=client.post("/learning/courses/INT1339/"+operation,headers=headers(),json=generation())
    assert result.status_code==403 and state==before and orch.generate.await_count==1


@pytest.mark.asyncio
async def test_real_receipt_validator_rejects_shape_only_and_expired_context(team):
    _,store,_,orch,pub,_,_,auth=team
    request=Request({"type":"http","headers":[(b"authorization",b"Bearer A")]})
    access=auth(request); scope=access.scope("INT1339")
    service=LearningGenerationService(QuizService(orch),FlashcardService(orch),store.quizzes,store.evidence,
        context_validator=lambda s,c:pub.validate_learning_context(s,c,access))
    with pub.context(scope,"Python") as context:
        learning=pub.learning_context(context)
        forged=learning.model_copy(update={"text":"forged text"})
        with pytest.raises(ValueError,match="learning_context_rejected"):
            await service._context(learning.scope,forged)
        assert pub.validate_learning_context(learning.scope,learning,access) is True
    with pytest.raises(ValueError,match="learning_context_rejected"):
        await service._context(learning.scope,learning)
    orch.generate.assert_not_awaited()


def test_concurrent_complete_scans_preserve_one_active_version(team):
    client,_,_,_,pub,engine,_,_=team
    engine.publish.reset_mock()
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:sync(client),range(2)))
    assert all(r.status_code==200 for r in results)
    assert len([r for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"])==1
    engine.publish.assert_called_once()


def test_internal_ingestion_uses_same_publication_and_stable_identity(team):
    _,_,_,_,pub,_,moodle,_=team
    from moodle_adapter import MoodleAdapter
    from moodle_ingestion_router import create_moodle_ingestion_router
    adapter=MoodleAdapter(BASE,"operator-service")
    adapter._call_ws=MagicMock(side_effect=lambda function, **kwargs:
        {"courses":[{"id":9,"shortname":"INT1339"}]} if function=="core_course_get_enrolled_courses_by_timeline_classification" else
        {"resources":[{"id":1,"contentfiles":[{"filename":"internal.md","fileurl":BASE+"/file.md","mimetype":"text/markdown","timemodified":123}]}]})
    adapter._download_file=MagicMock(return_value=MagicMock(content=b"internal full lecture",headers={"Content-Type":"text/markdown"}))
    adapter.list_file_resources=MagicMock(return_value=[{"resource_id":1}])
    service=DeepTutorService(pub.config,MagicMock())
    app=FastAPI(); app.include_router(create_moodle_ingestion_router(adapter,service,service_token="operator",publication_service=pub))
    client=TestClient(app,headers={"X-Internal-Api-Key":"operator"})
    result=client.post("/moodle/resources/ingest",json={"course_id_moodle":9,"resource_id":1})
    assert result.status_code==200 and result.json()["document_id"]==DOC
    assert next(r for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE").source_version_hint=="123"
    assert client.get("/moodle/courses/9/resources").json()[0]["sync_status"]=="indexed"
    assert client.delete("/moodle/courses/9/resources/1").status_code==200
    assert not [r for r in pub.ledger.snapshot().records.values() if r.lifecycle.value=="ACTIVE"]
