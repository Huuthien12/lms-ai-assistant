from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from moodle_ingestion_router import create_moodle_ingestion_router
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger


def discovery_app(service_token="test-discovery-token"):
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
    app = FastAPI()
    app.include_router(create_moodle_ingestion_router(
        moodle,
        service,
        ledger=MoodleIngestionLedger(service.config.runtime_dir),
        service_token=service_token,
    ))
    return app, moodle


@pytest.mark.asyncio
async def test_moodle_discovery_requires_a_valid_internal_credential():
    app, moodle = discovery_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.get("/moodle/courses")
        invalid = await client.get("/moodle/courses", headers={"X-Internal-Api-Key": "wrong"})
        allowed = await client.get("/moodle/courses", headers={"X-Internal-Api-Key": "test-discovery-token"})

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert allowed.status_code == 200
    assert allowed.json() == moodle.list_courses.return_value
    moodle.list_courses.assert_called_once()


@pytest.mark.asyncio
async def test_moodle_discovery_fails_closed_when_server_token_is_unconfigured():
    app, moodle = discovery_app(service_token=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/moodle/courses", headers={"X-Internal-Api-Key": "any-value"})

    assert response.status_code == 503
    moodle.list_courses.assert_not_called()


@pytest.mark.asyncio
async def test_moodle_discovery_returns_only_safe_public_fields_for_valid_service():
    app, _ = discovery_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resources = await client.get("/moodle/courses/5/resources", headers={"X-Internal-Api-Key": "test-discovery-token"})

    assert resources.status_code == 200
    resources = resources.json()
    assert [item["format"] for item in resources] == ["PDF", "DOCX", "PPTX", "MD", "UNSUPPORTED"]
    assert all(item["sync_status"] == "not_synced" and item["kb_id"] == "lms-int2001" for item in resources)
    assert "token" not in str(resources).lower() and "sha256" not in str(resources).lower()
