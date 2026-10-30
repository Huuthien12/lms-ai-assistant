from dataclasses import replace
from pathlib import Path
import subprocess
import time
from unittest.mock import MagicMock
import pytest
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import AuthorizedCourseScope, NormalizedDocument, DocumentInput
from deeptutor_integration.document_normalizer import source_sha256, artifact_sha256
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.full_source_adapter import DeepTutorFullSourceAdapter
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.verified_publication import VerifiedPublicationService
from deeptutor_integration.verified_context import verify_raw_chunks, build_context


@pytest.fixture
def publication(tmp_path):
    adapter=MagicMock(); stored={}
    def publish(kb,path):
        data={"provider":"llamaindex","index_version":"version-test","publication_ref":kb,
              "chunks":[{"chunk_id":"real-node","content":path.read_text(encoding="utf-8")} ]}
        stored[kb]=data; return data
    adapter.publish.side_effect=publish
    adapter.retrieve.side_effect=lambda kb,q,**kwargs:stored[kb]
    service=VerifiedPublicationService(DeepTutorConfig(tmp_path,tmp_path/"engine",tmp_path/"cli",tmp_path/"runtime"),adapter)
    scope=AuthorizedCourseScope(9,"INT1339","int1339-python","owner-A","https://moodle.test")
    return service,scope,adapter


def doc(content="OLD "+"full chunk "*60,document_id="1",filename="lecture.md"):
    return NormalizedDocument(document_id=document_id,course_id="INT1339",original_filename=filename,
        original_mime_type="text/markdown",sha256=source_sha256(content.encode()),artifact_sha256=artifact_sha256(content),
        markdown=content,normalizer_version="test/v1")


def test_publish_idempotent_full_chunk_update_delete(publication):
    service,scope,adapter=publication
    first=service.publish(scope,doc())
    assert first["status"]=="ACTIVE"
    assert service.publish(scope,doc())["action"]=="deduplicated"
    adapter.publish.assert_called_once()
    with service.context(scope,"question") as context:
        assert len(context.chunks[0].content)>200
        assert context.chunks[0].content==doc().markdown
        assert context.citations()[0]["verification_status"]=="VERIFIED_ACTIVE"
    service.publish(scope,doc("NEW "+"full context "*50))
    with service.context(scope,"question") as context:
        assert "NEW" in context.text() and "OLD" not in context.text()
    assert sorted(r.lifecycle.value for r in service.ledger.snapshot().records.values())==["ACTIVE","SUPERSEDED"]
    service.delete(scope,"1")
    with service.context(scope,"question") as context: assert not context.chunks


def test_failed_update_keeps_previous_active(publication):
    service,scope,adapter=publication; service.publish(scope,doc())
    adapter.publish.side_effect=DeepTutorError("retrieval_failure","Safe failure.",status_code=502)
    with pytest.raises(DeepTutorError): service.publish(scope,doc("changed"))
    with service.context(scope,"question") as context: assert "OLD" in context.text()
    assert sorted(r.lifecycle.value for r in service.ledger.snapshot().records.values())==["ACTIVE","FAILED"]


@pytest.mark.parametrize("mutation", ["course","kb","namespace","numeric","unknown","hash","version","deleted"])
def test_wrong_or_inactive_provenance_rejected(publication,mutation):
    service,scope,adapter=publication; service.publish(scope,doc())
    record=next(iter(service.ledger.snapshot().records.values()))
    raw=adapter.retrieve(record.provider_publication_ref,"q")
    if mutation in {"course","kb","namespace","numeric"}:
        field={"course":"course_key","kb":"kb_name","namespace":"source_namespace","numeric":"moodle_course_id"}[mutation]
        scope=replace(scope,**{field:10 if field=="moodle_course_id" else "other"})
    elif mutation=="unknown": raw={**raw,"chunks":[{"chunk_id":"unknown","content":"text"}]}
    elif mutation=="hash": raw={**raw,"chunks":[{"chunk_id":"real-node","content":"tampered"}]}
    elif mutation=="version": raw={**raw,"index_version":"old"}
    else: record=record.model_copy(update={"lifecycle":"DELETED"})
    with pytest.raises(DeepTutorError): verify_raw_chunks(record,scope,raw)


@pytest.mark.parametrize("identifier", ["../escape","..","C:\\escape","a/b","a\\b"])
def test_document_materialization_contains_resource_paths(tmp_path,identifier):
    config=DeepTutorConfig(tmp_path,tmp_path/"engine",tmp_path/"cli",tmp_path/"runtime")
    service=DeepTutorService(config)
    with pytest.raises(DeepTutorError):
        service._document_path(DocumentInput(course_id="INT1339",document_id=identifier,filename="doc.md",content="text"))
    assert not (tmp_path/"escape").exists()


def test_symlink_staging_parent_escape_is_rejected(tmp_path):
    outside=tmp_path/"outside"; outside.mkdir()
    root=tmp_path/"runtime"; root.mkdir()
    try: (root/"documents").symlink_to(outside,target_is_directory=True)
    except OSError:
        import os,subprocess
        if os.name!="nt": raise
        link=str(root/"documents").replace("'","''"); destination=str(outside).replace("'","''")
        subprocess.run(["powershell","-NoProfile","-Command",f"New-Item -ItemType Junction -Path '{link}' -Target '{destination}' | Out-Null"],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    service=DeepTutorService(DeepTutorConfig(tmp_path,tmp_path/"engine",tmp_path/"cli",root))
    with pytest.raises(DeepTutorError):
        service._document_path(DocumentInput(course_id="INT1339",document_id="1",filename="doc.md",content="text"))


def test_unexpected_retrieval_failure_is_controlled(publication):
    service,scope,adapter=publication; service.publish(scope,doc())
    adapter.retrieve.side_effect=RuntimeError("private dependency failure")
    with pytest.raises(DeepTutorError) as error:
        with service.context(scope,"q"): pytest.fail("No context after failure")
    assert error.value.status_code==502 and "private" not in str(error.value)


def test_expired_retrieval_budget_stops_before_adapter(publication):
    service,scope,adapter=publication; service.publish(scope,doc())
    adapter.retrieve.reset_mock()
    with pytest.raises(DeepTutorError) as error:
        with service.context(scope,"q",deadline=time.monotonic()-1):
            pytest.fail("No context after timeout")
    assert error.value.code=="retrieval_timeout" and error.value.status_code==504
    adapter.retrieve.assert_not_called()


def test_full_source_timeout_is_safe_and_forwards_budget(tmp_path,monkeypatch):
    python=tmp_path/"engine"/".venv"/"Scripts"/"python.exe"
    python.parent.mkdir(parents=True); python.touch()
    config=DeepTutorConfig(tmp_path,tmp_path/"engine",tmp_path/"cli",tmp_path/"runtime")
    seen={}
    def timeout(*args,**kwargs):
        seen["timeout"]=kwargs["timeout"]
        raise subprocess.TimeoutExpired(args[0],kwargs["timeout"])
    monkeypatch.setattr(subprocess,"run",timeout)
    with pytest.raises(DeepTutorError) as error:
        DeepTutorFullSourceAdapter(config).retrieve("kb","q",timeout_seconds=0.25)
    assert seen["timeout"]==0.25
    assert error.value.code=="retrieval_timeout" and error.value.status_code==504


def test_context_ranks_globally_before_applying_whole_chunk_budget(publication):
    service,scope,_=publication
    service.publish(scope,doc("One complete chunk"))
    with service.context(scope,"q") as context:
        chunk=context.chunks[0]
        low=replace(chunk,score=0.1)
        high=replace(chunk,score=0.9,chunk_id="high")
        selected=build_context(scope,"q",[low,high],max_characters=len(chunk.content)+len(chunk.source_ref)+4)
        assert selected.chunks==(high,)


def test_chapter_context_retrieves_only_selected_active_document(publication):
    service,scope,adapter=publication
    service.publish(scope,doc("Chapter one",document_id="chapter-1",filename="Chuong 1.pdf"))
    service.publish(scope,doc("Chapter two",document_id="chapter-2",filename="Chuong 2.pdf"))
    adapter.retrieve.reset_mock()
    with service.context(scope,"question",document_id="chapter-2") as context:
        assert len(context.chunks)==1 and context.chunks[0].document_id=="chapter-2"
    assert adapter.retrieve.call_count==1
    with pytest.raises(DeepTutorError,match="selected chapter") as error:
        with service.context(scope,"question",document_id="missing"):
            pytest.fail("No retrieval for an invalid chapter")
    assert error.value.status_code==422
