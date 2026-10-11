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
    def add_document(self, kb_id, document_path, metadata=None): self.added.append((kb_id, document_path))
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

    def test_config_empty_path_overrides_use_defaults(self):
        with TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"DEEPTUTOR_DIR": "", "DEEPTUTOR_EXE": "", "DEEPTUTOR_RUNTIME_DIR": ""},
            clear=True,
        ):
            config = DeepTutorConfig.from_env(Path(tmp))
            self.assertEqual(config.deeptutor_dir, Path(tmp).resolve() / "DeepTutor")
            self.assertEqual(config.executable, Path(tmp).resolve() / "DeepTutor" / ".venv" / "Scripts" / "deeptutor.exe")
            self.assertEqual(config.runtime_dir, Path(tmp).resolve() / ".deeptutor-runtime")

    def test_health_unavailable_without_process(self):
        with TemporaryDirectory() as tmp:
            base = self.make_service(Path(tmp))
            service = self.make_service(Path(tmp), CliDeepTutorAdapter(base.config))
            self.assertEqual(service.health()["status"], "unavailable")

    def test_adapter_prefers_venv_python_module_cli(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            deeptutor_dir = root / "DeepTutor"
            python_executable = deeptutor_dir / ".venv" / "Scripts" / "python.exe"
            python_executable.parent.mkdir(parents=True)
            python_executable.touch()
            executable = deeptutor_dir / ".venv" / "Scripts" / "deeptutor.exe"
            executable.touch()
            config = DeepTutorConfig(root, deeptutor_dir, executable, root / "runtime", 30)
            adapter = CliDeepTutorAdapter(config)
            with patch("deeptutor_integration.adapter.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = "[]"
                run.return_value.stderr = ""
                self.assertEqual(adapter.list_knowledge_bases(), [])
            self.assertEqual(
                run.call_args.args[0],
                [str(python_executable), "-m", "deeptutor_cli.main", "kb", "list", "--format", "json"],
            )

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

    def test_public_error_contract_hides_internal_details(self):
        error = DeepTutorError("process_failure", "DeepTutor command failed.", details={"reason": "D:/private/token=secret"})
        self.assertEqual(error.as_dict(), {"code": "process_failure", "message": "DeepTutor command failed."})

    def test_course_knowledge_base_mapping(self):
        self.assertEqual(DeepTutorService.kb_name("INT1339"), "int1339-python")
        self.assertEqual(DeepTutorService.kb_name("INT1339", "int1339-python"), "int1339-python")
        self.assertEqual(DeepTutorService.kb_name("MATH101"), "lms-math101")
        self.assertEqual(DeepTutorService.kb_name("MATH101", "lms-math101"), "lms-math101")
        with self.assertRaisesRegex(DeepTutorError, "does not match"):
            DeepTutorService.kb_name("INT1339", "lms-int1339")
        with self.assertRaisesRegex(DeepTutorError, "does not match"):
            DeepTutorService.kb_name("MATH101", "int1339-python")
        with self.assertRaisesRegex(DeepTutorError, "Course id is invalid"):
            DeepTutorService.kb_name("MATH101!")

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
            self.assertEqual(adapter.created[0][0], "int1339-python")
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

    def test_ingest_moodle_document_stages_pdf_and_preserves_contract(self):
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            normalized = {
                "course_id": "INT1339", "document_id": "42", "filename": "functions.pdf",
                "mime_type": "application/pdf", "source": "moodle",
                "metadata": {
                    "course_name": "Python", "moodle_file_size": 4,
                    "token": "secret", "download_url": "https://moodle.example/private.pdf",
                },
                "token": "secret", "download_url": "https://moodle.example/private.pdf",
            }
            captured = []

            def ingest(document):
                path = Path(document.path)
                self.assertTrue(path.is_file())
                self.assertTrue(path.is_relative_to(service.config.runtime_dir.resolve()))
                self.assertTrue(path.is_relative_to(service.config.repository_root.resolve()))
                self.assertEqual(path.suffix, ".pdf")
                self.assertEqual(path.read_bytes(), b"%PDF")
                captured.append(document)
                return {"status": "ready"}

            with patch.object(service, "ingest_document", side_effect=ingest) as delegated:
                self.assertEqual(service.ingest_moodle_document(normalized, b"%PDF", kb_id="int1339-python"), {"status": "ready"})
            delegated.assert_called_once()
            document = captured[0]
            self.assertEqual((document.document_id, document.course_id, document.filename, document.kb_id),
                             ("42", "INT1339", "functions.pdf", "int1339-python"))
            self.assertEqual(document.metadata, {"course_name": "Python", "moodle_file_size": 4})
            self.assertNotIn("token", document.model_dump())
            self.assertNotIn("download_url", document.model_dump())
            self.assertFalse(Path(document.path).exists())

    def test_ingest_moodle_document_rejects_invalid_bytes(self):
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            normalized = {"course_id": "c", "document_id": "d", "filename": "document.pdf"}
            for value in (None, b"", "not bytes"):
                with self.assertRaisesRegex(DeepTutorError, "PDF content"):
                    service.ingest_moodle_document(normalized, value)  # type: ignore[arg-type]

    def test_ingest_moodle_document_cleans_up_after_ingestion_failure(self):
        with TemporaryDirectory() as tmp:
            service = self.make_service(Path(tmp))
            captured_path = None

            def fail(document):
                nonlocal captured_path
                captured_path = Path(document.path)
                self.assertTrue(captured_path.is_file())
                raise DeepTutorError("cli_failed", "CLI failed", status_code=502)

            normalized = {"course_id": "c", "document_id": "d", "filename": "document.pdf"}
            with patch.object(service, "ingest_document", side_effect=fail):
                with self.assertRaisesRegex(DeepTutorError, "CLI failed"):
                    service.ingest_moodle_document(normalized, b"%PDF")
            self.assertIsNotNone(captured_path)
            self.assertFalse(captured_path.exists())

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
