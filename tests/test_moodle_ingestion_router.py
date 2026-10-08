from __future__ import annotations

import sys
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.contracts import NormalizedDocument, SourceDocument
from deeptutor_integration.document_normalizer import DocumentNormalizer
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from moodle_ingestion_router import create_moodle_ingestion_router


SERVICE_TOKEN = "test-moodle-token"


class StubNormalizer:
    def normalize(self, source: SourceDocument) -> NormalizedDocument:
        return NormalizedDocument(
            document_id=source.document_id, course_id=source.course_id,
            original_filename=source.filename, original_mime_type=source.mime_type,
            source=source.source, metadata=source.metadata, sha256=sha256(source.content).hexdigest(),
            markdown=f"# {source.filename}", normalizer_version="test-v1",
        )


def source(filename="chapter.pdf", mime_type="application/pdf", content=b"original"):
    return SourceDocument(document_id="1", course_id="INT1339", filename=filename, mime_type=mime_type,
                          source="moodle", content=content, metadata={"course_name": "Python"})


def client(moodle_adapter, deeptutor_service, ledger=None, normalizer=None):
    app = FastAPI()
    ledger = ledger or MagicMock()
    if isinstance(ledger, MagicMock):
        ledger.contains.return_value = False
    app.include_router(create_moodle_ingestion_router(
        moodle_adapter, deeptutor_service, normalizer or StubNormalizer(), ledger, SERVICE_TOKEN
    ))
    return TestClient(app, headers={"X-Internal-Api-Key": SERVICE_TOKEN})


@pytest.mark.asyncio
async def test_ingestion_rejects_invalid_service_credentials_before_side_effects():
    moodle = MagicMock()
    normalizer = MagicMock()
    deeptutor = MagicMock()
    ledger = MagicMock()
    app = FastAPI()
    app.include_router(create_moodle_ingestion_router(
        moodle, deeptutor, normalizer, ledger, SERVICE_TOKEN
    ))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        missing = await http_client.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1})
        invalid = await http_client.post(
            "/moodle/resources/ingest",
            headers={"X-Internal-Api-Key": "wrong"},
            json={"course_id_moodle": 9, "resource_id": 1},
        )

    assert missing.status_code == invalid.status_code == 401
    moodle.get_source_document.assert_not_called()
    normalizer.normalize.assert_not_called()
    ledger.contains.assert_not_called()
    ledger.record.assert_not_called()
    deeptutor.ingest_document.assert_not_called()


@pytest.mark.asyncio
async def test_ingestion_fails_closed_without_a_configured_service_token():
    moodle = MagicMock()
    normalizer = MagicMock()
    deeptutor = MagicMock()
    ledger = MagicMock()
    app = FastAPI()
    app.include_router(create_moodle_ingestion_router(moodle, deeptutor, normalizer, ledger, ""))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        response = await http_client.post(
            "/moodle/resources/ingest",
            headers={"X-Internal-Api-Key": SERVICE_TOKEN},
            json={"course_id_moodle": 9, "resource_id": 1},
        )

    assert response.status_code == 503
    moodle.get_source_document.assert_not_called()
    normalizer.normalize.assert_not_called()
    ledger.contains.assert_not_called()
    ledger.record.assert_not_called()
    deeptutor.ingest_document.assert_not_called()


def test_ingests_normalized_markdown_without_secret_response_data():
    moodle = MagicMock()
    moodle.get_source_document.return_value = source(content=b"%PDF-exact-bytes")
    deeptutor = MagicMock()
    deeptutor.kb_name.return_value = "int1339-python"
    deeptutor.ingest_document.return_value = {
        "document_id": "1", "course_id": "INT1339", "kb_id": "int1339-python",
        "action": "add", "status": "ready", "metadata": {"course_name": "Python"},
    }

    response = client(moodle, deeptutor).post("/moodle/resources/ingest", json={
        "course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python",
    })

    assert response.status_code == 200
    moodle.get_source_document.assert_called_once_with(9, 1)
    document = deeptutor.ingest_document.call_args.args[0]
    assert document.filename.endswith(".md")
    assert document.content == "# chapter.pdf"
    assert document.metadata["original_filename"] == "chapter.pdf"
    assert document.metadata["original_sha256"] == sha256(b"%PDF-exact-bytes").hexdigest()
    assert response.json()["status"] == "indexed"
    response_text = response.text.lower()
    assert "token" not in response_text
    assert "http" not in response_text
    assert "staging" not in response_text


def test_supported_formats_handoff_markdown():
    cases = (
        ("chapter.pdf", "application/pdf"),
        ("chapter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("chapter.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("chapter.md", "text/markdown"),
    )
    for filename, mime_type in cases:
        moodle = MagicMock(); moodle.get_source_document.return_value = source(filename, mime_type)
        deeptutor = MagicMock(); deeptutor.kb_name.return_value = "int1339-python"
        deeptutor.ingest_document.return_value = {"kb_id": "int1339-python", "status": "ready"}
        response = client(moodle, deeptutor).post(
            "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
        )
        assert response.status_code == 200
        document = deeptutor.ingest_document.call_args.args[0]
        assert document.filename.endswith(".md")
        assert document.content == f"# {filename}"


def test_ingestion_forwards_the_optional_mapped_kb_name():
    moodle = MagicMock()
    moodle.get_source_document.return_value = source()
    deeptutor = MagicMock()
    deeptutor.kb_name.return_value = "int1339-python"
    deeptutor.ingest_document.return_value = {"kb_id": "int1339-python"}

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python"}
    )

    assert response.status_code == 200
    assert deeptutor.ingest_document.call_args.args[0].kb_id == "int1339-python"


def test_moodle_failure_does_not_call_deeptutor():
    moodle = MagicMock()
    moodle.get_source_document.side_effect = RuntimeError("private Moodle failure")
    deeptutor = MagicMock()

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "moodle_document_unavailable"
    deeptutor.ingest_document.assert_not_called()


def test_unexpected_moodle_failure_is_sanitized():
    moodle = MagicMock()
    moodle.get_source_document.side_effect = ValueError("D:/private/token=secret")
    deeptutor = MagicMock()

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "moodle_document_unavailable"
    assert "private" not in response.text.lower()
    assert "secret" not in response.text.lower()
    deeptutor.ingest_document.assert_not_called()


def test_deeptutor_failure_is_returned_as_typed_http_error():
    moodle = MagicMock()
    moodle.get_source_document.return_value = source()
    deeptutor = MagicMock()
    deeptutor.kb_name.return_value = "int1339-python"
    deeptutor.ingest_document.side_effect = DeepTutorError(
        "kb_not_ready", "Knowledge base is not ready.", status_code=409
    )

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "kb_not_ready"


def test_ppt_is_rejected_before_deeptutor():
    moodle = MagicMock(); moodle.get_source_document.return_value = source("chapter.ppt", "application/vnd.ms-powerpoint")
    deeptutor = MagicMock()
    response = client(moodle, deeptutor, normalizer=DocumentNormalizer()).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )
    assert response.status_code == 415
    deeptutor.ingest_document.assert_not_called()


def test_deduplicates_successful_source_hash_and_retries_failures():
    with TemporaryDirectory() as temporary:
        moodle = MagicMock(); moodle.get_source_document.return_value = source(content=b"first")
        deeptutor = MagicMock(); deeptutor.kb_name.return_value = "int1339-python"
        deeptutor.ingest_document.return_value = {"kb_id": "int1339-python", "status": "ready"}
        api = client(moodle, deeptutor, MoodleIngestionLedger(Path(temporary)))
        assert api.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}).json()["status"] == "indexed"
        assert api.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}).json()["status"] == "already_indexed"
        moodle.get_source_document.return_value = source(content=b"changed")
        assert api.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}).json()["status"] == "indexed"
        assert deeptutor.ingest_document.call_count == 2

        moodle.get_source_document.return_value = source(content=b"retry")
        deeptutor.ingest_document.side_effect = [DeepTutorError("failed", "private", status_code=502), {"kb_id": "int1339-python"}]
        assert api.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}).status_code == 502
        assert api.post("/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}).json()["status"] == "indexed"
