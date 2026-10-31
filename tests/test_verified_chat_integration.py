import sys
from pathlib import Path
import json
from unittest.mock import AsyncMock, MagicMock
from concurrent.futures import ThreadPoolExecutor
import httpx
import requests
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.services.ai.grounded_chat import GroundedChatService, GroundedChatResponse
from backend.services.ai.provider_base import LLMResult
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import AuthorizedCourseScope, NormalizedDocument
from deeptutor_integration.document_normalizer import source_sha256, artifact_sha256
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.verified_publication import VerifiedPublicationService
from deeptutor_integration.api import create_router
sys.path.insert(0,str(Path(__file__).parents[1]/"lms-dlu-demo"))
from course_query_auth import create_moodle_query_authorizer
from grounded_chat_router import create_grounded_chat_router


def document(text):
    return NormalizedDocument(course_id="INT1339",document_id="1",original_filename="lecture.md",
        original_mime_type="text/markdown",sha256=source_sha256(text.encode()),artifact_sha256=artifact_sha256(text),
        markdown=text,normalizer_version="test/v1")


@pytest.fixture
def runtime(tmp_path,monkeypatch):
    adapter=MagicMock(); indexed={}
    authorization_state={"revoked":False}; adapter.authorization_state=authorization_state
    def publish(kb,path):
        raw={"provider":"llamaindex","index_version":"version-test","publication_ref":kb,
             "chunks":[{"chunk_id":"real-node","content":path.read_text(encoding="utf-8")} ]}
        indexed[kb]=raw; return raw
    adapter.publish.side_effect=publish; adapter.retrieve.side_effect=lambda kb,q,**kwargs:indexed[kb]
    config=DeepTutorConfig(tmp_path,tmp_path/"engine",tmp_path/"cli",tmp_path/"runtime")
    publications=VerifiedPublicationService(config,adapter)
    scope=AuthorizedCourseScope(9,"INT1339","int1339-python","owner","https://moodle.test")
    service=DeepTutorService(config,MagicMock())
    def moodle(url,**kw):
        token=kw["data"]["wstoken"]
        if token=="down": raise requests.ConnectionError("SECRET")
        if token not in {"A","B"}: return httpx.Response(200,json={"errorcode":"invalidtoken"})
        uid=1 if token=="A" else 2
        if kw["data"]["wsfunction"]=="core_webservice_get_site_info": return httpx.Response(200,json={"userid":uid,"siteurl":"https://moodle.test","functions":[{"name":"core_enrol_get_users_courses"}]})
        courses=[] if uid==1 and authorization_state["revoked"] else [{"id":9 if uid==1 else 10,"shortname":"INT1339" if uid==1 else "OTHER"}]
        return httpx.Response(200,json=courses)
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.post",moodle)
    authorizer=create_moodle_query_authorizer(service,"https://moodle.test")
    orch=MagicMock(); orch.generate=AsyncMock(return_value=LLMResult("success","fake","fake","Answer",0))
    app=FastAPI(); app.include_router(create_router(service,query_authorizer=authorizer,publication_service=publications))
    app.include_router(create_grounded_chat_router(service,GroundedChatService(orch),query_authorizer=authorizer,publication_service=publications))
    return TestClient(app),publications,scope,adapter,orch,indexed


@pytest.mark.parametrize("path",["/chat/grounded","/lms/chat"])
def test_full_verified_context_citations_update_and_delete_never_send_old_text(runtime,path):
    client,pub,scope,adapter,orch,_=runtime
    pub.publish(scope,document("OLD " + "complete text "*50+"TAIL_AFTER_200"))
    body={"question":"Question","course_id":"int1339"}; headers={"Authorization":"Bearer A"}
    first=client.post(path,json=body,headers=headers)
    assert first.status_code==200
    assert "TAIL_AFTER_200" in orch.generate.call_args.kwargs["prompt"]
    citation=first.json()["sources"][0]
    assert citation["document_id"]=="1" and citation["verification_status"]=="VERIFIED_ACTIVE"
    assert citation["source_ref"] == json.loads(orch.generate.call_args.kwargs["prompt"])["reference_data"][0]["source_id"]
    pub.publish(scope,document("NEW only"))
    assert client.post(path,json=body,headers=headers).status_code==200
    assert "NEW only" in orch.generate.call_args.kwargs["prompt"] and "OLD" not in orch.generate.call_args.kwargs["prompt"]
    pub.delete(scope,"1"); orch.generate.reset_mock(); adapter.retrieve.reset_mock()
    deleted=client.post(path,json=body,headers=headers)
    assert deleted.status_code==200 and deleted.json()["sources"]==[]
    orch.generate.assert_not_awaited(); adapter.retrieve.assert_not_called()


@pytest.mark.parametrize("token,status",[(None,401),("invalid",401),("B",403),("down",503)])
def test_denied_requests_have_zero_raw_retrieval_and_llm(runtime,token,status):
    client,pub,scope,adapter,orch,_=runtime
    pub.publish(scope,document("context")); adapter.retrieve.reset_mock()
    headers={} if token is None else {"Authorization":"Bearer "+token}
    r=client.post("/lms/chat",json={"question":"Question","course_id":"INT1339"},headers=headers)
    assert r.status_code==status
    adapter.retrieve.assert_not_called(); orch.generate.assert_not_awaited()


def test_tampered_chunk_never_enters_prompt(runtime):
    client,pub,scope,adapter,orch,indexed=runtime; pub.publish(scope,document("trusted"))
    next(iter(indexed.values()))["chunks"][0]["content"]="TAMPERED SECRET"
    r=client.post("/lms/chat",json={"question":"Question","course_id":"INT1339"},headers={"Authorization":"Bearer A"})
    assert r.status_code==409 and "SECRET" not in r.text
    orch.generate.assert_not_awaited()


def test_concurrent_same_document_publication_is_idempotent(runtime):
    _,pub,scope,adapter,_,_=runtime
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:pub.publish(scope,document("same")),range(2)))
    assert {r["action"] for r in results}=={"published","deduplicated"}
    assert len(pub.documents(scope))==1
    adapter.publish.assert_called_once()


@pytest.mark.parametrize("mode,status",[("failure",502),("reindex",409),("empty",200)])
def test_raw_retrieval_error_and_empty_semantics_no_llm(runtime,mode,status):
    from deeptutor_integration.errors import DeepTutorError
    client,pub,scope,adapter,orch,indexed=runtime; pub.publish(scope,document("trusted"))
    if mode=="empty": next(iter(indexed.values()))["chunks"]=[]
    else: adapter.retrieve.side_effect=DeepTutorError("kb_not_ready" if mode=="reindex" else "retrieval_failure","Safe failure.",status_code=status)
    response=client.post("/lms/chat",json={"question":"Question","course_id":"INT1339"},headers={"Authorization":"Bearer A"})
    assert response.status_code==status
    orch.generate.assert_not_awaited()


def test_explicit_foreign_kb_rejected_before_raw_retrieval(runtime):
    client,pub,scope,adapter,orch,_=runtime; pub.publish(scope,document("trusted")); adapter.retrieve.reset_mock()
    response=client.post("/lms/chat",json={"question":"Question","course_id":"INT1339","kb_name":"other"},headers={"Authorization":"Bearer A"})
    assert response.status_code==422
    adapter.retrieve.assert_not_called(); orch.generate.assert_not_awaited()


def test_cleanup_and_selection_preserve_exact_verified_provenance(runtime):
    client,pub,scope,adapter,orch,indexed=runtime
    originals = ["Unrelated recursion", "Phép toán + - * / (cid:42)", "Phép toán + - * / (cid:42)",
                 "Điều kiện rẽ nhánh", "Kiểm tra chia cho 0"]
    for i, text in enumerate(originals):
        pub.publish(scope,document(text).model_copy(update={"document_id":str(i)}))
    scores = [0.1, 0.95, 0.9, 0.8, 0.7]
    for raw,score in zip(indexed.values(),scores):
        raw["chunks"][0]["score"]=score
    response=client.post("/lms/chat",json={"question":"Giải thích phép toán","course_id":"INT1339"},
                         headers={"Authorization":"Bearer A"})
    assert response.status_code==200
    sources=response.json()["sources"]
    assert [s["document_id"] for s in sources]==["1","3","4"]
    assert "(cid:" not in sources[0]["preview"] and "�" in sources[0]["preview"]
    prompt=json.loads(orch.generate.call_args.kwargs["prompt"])
    assert [s["source_id"] for s in prompt["reference_data"]]==[s["source_ref"] for s in sources]
    records={r.document_id:r for r in pub.ledger.snapshot().records.values()}
    for source in sources:
        record=records[source["document_id"]]
        assert source["document_version_id"]==record.document_version_id
        assert source["chunk_id"]==record.chunk_manifest[0].chunk_id
        assert source["content_sha256"]==record.chunk_manifest[0].content_sha256
        assert source["title"]==record.original_filename
    assert [raw["chunks"][0]["content"] for raw in indexed.values()]==originals


def test_chat_cannot_return_unverified_source_identity(runtime,monkeypatch):
    client,pub,scope,adapter,orch,_=runtime
    pub.publish(scope,document("Trusted content"))
    monkeypatch.setattr(GroundedChatService,"chat",AsyncMock(return_value=GroundedChatResponse(
        "success","Answer",scope.course_key,scope.kb_name,[{"source_id":"fabricated"}],
        {"provider":"fake","model":"fake","fallback_used":False})))
    response=client.post("/lms/chat",json={"question":"Question","course_id":"INT1339"},
                         headers={"Authorization":"Bearer A"})
    assert response.status_code==502 and "fabricated" not in response.text
