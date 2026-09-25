from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from pydantic import ValidationError

from deeptutor_integration.adapter import CliDeepTutorAdapter
from deeptutor_integration.api import create_router
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import DocumentInput, KnowledgeBaseInput, QueryInput
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService

READY = {"name": "lms-int1339", "status": "ready", "statistics": {"rag_initialized": True}}


class FakeAdapter:
    def __init__(self, info=None):
        self.info = info
        self.created = []
        self.added = []

    def health(self): return {"available": True, "status": "available"}
    def list_knowledge_bases(self): return [self.info] if self.info else []
    def get_knowledge_base(self, kb_id): return self.info
    def create_knowledge_base(self, kb_id, document_path):
        self.created.append((kb_id, document_path)); self.info = READY
    def add_document(self, kb_id, document_path): self.added.append((kb_id, document_path))
    def search(self, kb_id, question): return {"answer": "grounded", "sources": []}


class DeepTutorIntegrationTests(unittest.TestCase):
    def make_service(self, root: Path, adapter=None):
        config = DeepTutorConfig(root, root / "DeepTutor", root / "deeptutor.exe", root / "runtime", 30)
        return DeepTutorService(config, adapter or FakeAdapter())

    def test_config_paths_and_env_override(self):
        with TemporaryDirectory() as tmp, patch.dict(os.environ, {"DEEPTUTOR_TIMEOUT_SECONDS": "12"}, clear=True):
            config = DeepTutorConfig.from_env(Path(tmp))
            self.assertEqual(config.deeptutor_dir, Path(tmp).resolve() / "DeepTutor")
            self.assertEqual(config.runtime_dir, Path(tmp).resolve() / ".deeptutor-runtime")
            self.assertEqual(config.command_timeout_seconds, 12)

    def test_health_unavailable_without_process(self):
        with TemporaryDirectory() as tmp:
            base = self.make_service(Path(tmp))
            service = self.make_service(Path(tmp), CliDeepTutorAdapter(base.config))
            self.assertEqual(service.health()["status"], "unavailable")

    def test_document_validation(self):
        with self.assertRaises(ValidationError):
            DocumentInput(document_id="1", course_id="c", filename="a.txt")
        with self.assertRaises(ValidationError):
            DocumentInput(document_id="1", course_id="c", filename="../a.txt", content="x")

    def test_kb_course_must_match_document(self):
        document = DocumentInput(document_id="1", course_id="a", filename="a.txt", content="x")
        with self.assertRaises(ValidationError): KnowledgeBaseInput(course_id="b", document=document)

    def test_query_validation(self):
        with self.assertRaises(ValidationError): QueryInput(course_id="c", question="")

    def test_query_missing_and_unready_kb(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(DeepTutorError, "not found"):
                self.make_service(Path(tmp)).query(QueryInput(course_id="INT1339", question="hello"))
            adapter = FakeAdapter({"name": "lms-int1339", "status": "building", "statistics": {}})
            with self.assertRaisesRegex(DeepTutorError, "not ready"):
                self.make_service(Path(tmp), adapter).query(QueryInput(course_id="INT1339", question="hello"))

    def test_ingest_create_then_add(self):
        with TemporaryDirectory() as tmp:
            adapter = FakeAdapter(); service = self.make_service(Path(tmp), adapter)
            request = DocumentInput(document_id="d1", course_id="INT1339", filename="lesson.txt", content="lesson")
            self.assertEqual(service.ingest_document(request)["action"], "create")
            self.assertEqual(service.ingest_document(request)["action"], "add")

    def test_unsupported_document_error(self):
        with TemporaryDirectory() as tmp:
            request = DocumentInput(document_id="d1", course_id="c", filename="program.exe", content="x")
            with self.assertRaises(DeepTutorError) as raised: self.make_service(Path(tmp)).ingest_document(request)
            self.assertEqual((raised.exception.code, raised.exception.status_code), ("unsupported_document", 415))

    def test_document_path_cannot_escape_workspace(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"; root.mkdir()
            outside = Path(tmp) / "outside.txt"; outside.write_text("x", encoding="utf-8")
            request = DocumentInput(document_id="d1", course_id="c", filename="outside.txt", path=str(outside))
            with self.assertRaises(DeepTutorError) as raised: self.make_service(root).ingest_document(request)
            self.assertEqual(raised.exception.code, "invalid_document")

    def test_router_contract(self):
        with TemporaryDirectory() as tmp:
            router = create_router(self.make_service(Path(tmp)))
            app = FastAPI(); app.include_router(router)
            routes = {(r.path, m) for r in router.routes for m in getattr(r, "methods", set())}
            expected = {("/deeptutor/documents", "POST"), ("/deeptutor/knowledge-bases", "POST"),
                        ("/deeptutor/query", "POST"), ("/deeptutor/health", "GET"),
                        ("/deeptutor/status", "GET")}
            self.assertTrue(expected <= routes)


if __name__ == "__main__": unittest.main()
