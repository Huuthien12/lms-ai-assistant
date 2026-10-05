from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from moodle_ingestion_router import create_moodle_ingestion_router
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger


def test_moodle_discovery_returns_only_safe_public_fields():
    moodle = MagicMock()
    moodle.list_courses.return_value = [{"id": 5, "shortname": "INT2001", "fullname": "AI"}]
    moodle.get_course.return_value = {"id": 5, "shortname": "INT2001", "fullname": "AI"}
    moodle.list_file_resources.return_value = [
        {"resource_id": 10, "filename": "chapter.pdf", "mime_type": "application/pdf", "format": "PDF"},
        {"resource_id": 11, "filename": "chapter.docx", "mime_type": "application/docx", "format": "DOCX"},
        {"resource_id": 12, "filename": "slides.pptx", "mime_type": "application/pptx", "format": "PPTX"},
        {"resource_id": 13, "filename": "notes.md", "mime_type": "text/markdown", "format": "MD"},
        {"resource_id": 14, "filename": "legacy.ppt", "mime_type": "application/ppt", "format": "UNSUPPORTED"},
    ]
    service = MagicMock(); service.kb_name.return_value = "lms-int2001"; service.config.runtime_dir = Path(TemporaryDirectory().name)
    app = FastAPI(); app.include_router(create_moodle_ingestion_router(moodle, service, ledger=MoodleIngestionLedger(service.config.runtime_dir)))
    client = TestClient(app)
    assert client.get("/moodle/courses").json() == moodle.list_courses.return_value
    resources = client.get("/moodle/courses/5/resources").json()
    assert [item["format"] for item in resources] == ["PDF", "DOCX", "PPTX", "MD", "UNSUPPORTED"]
    assert all(item["sync_status"] == "not_synced" and item["kb_id"] == "lms-int2001" for item in resources)
    assert "token" not in str(resources).lower() and "sha256" not in str(resources).lower()
