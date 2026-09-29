from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor_integration.errors import DeepTutorError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from moodle_ingestion_router import create_moodle_ingestion_router


def client(moodle_adapter, deeptutor_service):
    app = FastAPI()
    app.include_router(create_moodle_ingestion_router(moodle_adapter, deeptutor_service))
    return TestClient(app)


def test_ingests_exact_moodle_document_and_pdf_bytes_without_secret_response_data():
    normalized_doc = {
        "course_id": "INT1339", "document_id": "1", "filename": "chapter.pdf",
        "mime_type": "application/pdf", "source": "moodle", "metadata": {"course_name": "Python"},
    }
    pdf_bytes = b"%PDF-exact-bytes"
    moodle = MagicMock()
    moodle.get_normalized_document.return_value = (normalized_doc, pdf_bytes)
    deeptutor = MagicMock()
    deeptutor.ingest_moodle_document.return_value = {
        "document_id": "1", "course_id": "INT1339", "kb_id": "int1339-python",
        "action": "add", "status": "ready", "metadata": {"course_name": "Python"},
    }

    response = client(moodle, deeptutor).post("/moodle/resources/ingest", json={
        "course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python",
    })

    assert response.status_code == 200
    moodle.get_normalized_document.assert_called_once_with(9, 1)
    deeptutor.ingest_moodle_document.assert_called_once_with(
        normalized_doc, pdf_bytes, kb_id="int1339-python"
    )
    assert response.json() == deeptutor.ingest_moodle_document.return_value
    response_text = response.text.lower()
    assert "token" not in response_text
    assert "http" not in response_text
    assert "staging" not in response_text


def test_ingestion_forwards_the_optional_mapped_kb_name():
    moodle = MagicMock()
    moodle.get_normalized_document.return_value = ({"course_id": "INT1339"}, b"%PDF")
    deeptutor = MagicMock()
    deeptutor.ingest_moodle_document.return_value = {"kb_id": "int1339-python"}

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python"}
    )

    assert response.status_code == 200
    assert deeptutor.ingest_moodle_document.call_args.kwargs["kb_id"] == "int1339-python"


def test_moodle_failure_does_not_call_deeptutor():
    moodle = MagicMock()
    moodle.get_normalized_document.side_effect = RuntimeError("private Moodle failure")
    deeptutor = MagicMock()

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "moodle_document_unavailable"
    deeptutor.ingest_moodle_document.assert_not_called()


def test_deeptutor_failure_is_returned_as_typed_http_error():
    moodle = MagicMock()
    moodle.get_normalized_document.return_value = ({"course_id": "INT1339"}, b"%PDF")
    deeptutor = MagicMock()
    deeptutor.ingest_moodle_document.side_effect = DeepTutorError(
        "kb_not_ready", "Knowledge base is not ready.", status_code=409
    )

    response = client(moodle, deeptutor).post(
        "/moodle/resources/ingest", json={"course_id_moodle": 9, "resource_id": 1}
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "kb_not_ready"
