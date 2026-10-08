from pathlib import Path
import sys
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from moodle_service_auth import create_moodle_service_dependency
from deeptutor_integration.api import create_router


TOKEN = "test-service-token"
DOCUMENT = {
    "document_id": "chapter-1",
    "course_id": "INT1339",
    "filename": "chapter.md",
    "content": "# Chapter 1",
}
KNOWLEDGE_BASE = {"course_id": "INT1339", "document": DOCUMENT}
WRITES = (
    ("/deeptutor/documents", DOCUMENT, "ingest_document"),
    ("/deeptutor/knowledge-bases", KNOWLEDGE_BASE, "create_knowledge_base"),
)


def write_app(service_token: str | None = TOKEN, inject_authorizer=True):
    service = MagicMock()
    service.ingest_document.return_value = {"kb_id": "int1339-python"}
    service.create_knowledge_base.return_value = {"kb_id": "int1339-python"}
    app = FastAPI()
    kwargs = {}
    if inject_authorizer:
        kwargs["write_authorizer"] = create_moodle_service_dependency(service_token)
    app.include_router(create_router(service, **kwargs))
    return app, service


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload", "method"), WRITES)
async def test_each_deeptutor_write_rejects_a_missing_or_invalid_service_key(endpoint, payload, method):
    app, service = write_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        missing = await client.post(endpoint, json=payload)
        invalid = await client.post(endpoint, headers={"X-Internal-Api-Key": "wrong"}, json=payload)

    assert missing.status_code == 401
    assert invalid.status_code == 401
    getattr(service, method).assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload", "method"), WRITES)
async def test_each_deeptutor_write_accepts_a_valid_service_key(endpoint, payload, method):
    app, service = write_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(endpoint, headers={"X-Internal-Api-Key": TOKEN}, json=payload)

    assert response.status_code == 200
    getattr(service, method).assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload", "method"), WRITES)
async def test_each_deeptutor_write_fails_closed_when_service_auth_is_unconfigured(endpoint, payload, method):
    app, service = write_app(service_token=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(endpoint, headers={"X-Internal-Api-Key": TOKEN}, json=payload)

    assert response.status_code == 503
    getattr(service, method).assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(("endpoint", "payload", "method"), WRITES)
async def test_each_deeptutor_write_fails_closed_without_an_injected_authorizer(endpoint, payload, method):
    app, service = write_app(inject_authorizer=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(endpoint, headers={"X-Internal-Api-Key": TOKEN}, json=payload)

    assert response.status_code == 503
    getattr(service, method).assert_not_called()


@pytest.mark.asyncio
async def test_deeptutor_read_routes_and_query_remain_unprotected():
    app, service = write_app()
    service.health.return_value = {"available": True}
    service.status.return_value = {"knowledge_bases": []}
    service.query.return_value = {"answer": "grounded"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        health = await client.get("/deeptutor/health")
        status = await client.get("/deeptutor/status")
        query = await client.post("/deeptutor/query", json={"course_id": "INT1339", "question": "What is Python?"})

    assert health.status_code == 200
    assert status.status_code == 200
    assert query.status_code == 200
