from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .adapter import CliDeepTutorAdapter, DeepTutorAdapter
from .config import DeepTutorConfig
from .contracts import DocumentInput, KnowledgeBaseInput, QueryInput
from .errors import DeepTutorError


class DeepTutorService:
    SUPPORTED_DOCUMENT_EXTENSIONS = {
        ".csv", ".docx", ".epub", ".htm", ".html", ".json",
        ".md", ".pdf", ".pptx", ".rtf", ".txt",
    }
    def __init__(self, config: DeepTutorConfig, adapter: DeepTutorAdapter | None = None) -> None:
        self.config = config
        self.adapter = adapter or CliDeepTutorAdapter(config)

    @staticmethod
    def kb_name(course_id: str, explicit: str | None = None) -> str:
        value = explicit or f"lms-{course_id}"
        normalized = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
        if not normalized:
            raise DeepTutorError("invalid_kb", "Knowledge-base id is invalid.", status_code=422)
        return normalized

    @staticmethod
    def _ready(info: dict[str, Any]) -> bool:
        stats = info.get("statistics") or {}
        return str(info.get("status", "")).lower() == "ready" and stats.get("rag_initialized") is True

    def health(self) -> dict[str, Any]:
        return self.adapter.health()

    def status(self, kb_id: str | None = None) -> dict[str, Any]:
        if kb_id:
            info = self.adapter.get_knowledge_base(kb_id)
            if info is None:
                raise DeepTutorError("kb_not_found", "Knowledge base was not found.", status_code=404)
            return {"knowledge_base": info, "ready": self._ready(info)}
        return {"runtime": self.health(), "knowledge_bases": self.adapter.list_knowledge_bases()}

    def _document_path(self, document: DocumentInput) -> Path:
        suffix = Path(document.filename).suffix.lower()
        if suffix not in self.SUPPORTED_DOCUMENT_EXTENSIONS:
            raise DeepTutorError(
                "unsupported_document",
                "Document type is not supported by the DeepTutor integration.",
                status_code=415,
                details={"extension": suffix or None},
            )
        if document.path:
            path = Path(document.path).expanduser().resolve()
            if not path.is_relative_to(self.config.repository_root.resolve()):
                raise DeepTutorError(
                    "invalid_document",
                    "Document path must be inside the project workspace.",
                    status_code=422,
                )
            if not path.is_file():
                raise DeepTutorError("invalid_document", "Document path does not exist.", status_code=422)
            return path
        self.config.runtime_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self.config.runtime_dir / "documents" / document.course_id / document.document_id
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / document.filename
        target.write_text(document.content or "", encoding="utf-8")
        return target

    def ingest_document(self, document: DocumentInput) -> dict[str, Any]:
        kb_id = self.kb_name(document.course_id, document.kb_id)
        path = self._document_path(document)
        info = self.adapter.get_knowledge_base(kb_id)
        action = "create"
        if info is None:
            self.adapter.create_knowledge_base(kb_id, path)
        elif self._ready(info):
            action = "add"
            self.adapter.add_document(kb_id, path)
        else:
            raise DeepTutorError("kb_not_ready", "Knowledge base is not ready.", status_code=409)
        final_info = self.adapter.get_knowledge_base(kb_id)
        if final_info is None or not self._ready(final_info):
            raise DeepTutorError("kb_not_ready", "Knowledge base did not become ready.", status_code=409)
        return {
            "document_id": document.document_id,
            "course_id": document.course_id,
            "kb_id": kb_id,
            "action": action,
            "status": final_info.get("status"),
            "metadata": document.metadata,
        }

    def create_knowledge_base(self, request: KnowledgeBaseInput) -> dict[str, Any]:
        kb_id = self.kb_name(request.course_id, request.kb_id)
        if self.adapter.get_knowledge_base(kb_id) is not None:
            raise DeepTutorError("kb_exists", "Knowledge base already exists.", status_code=409)
        document = request.document.model_copy(update={"kb_id": kb_id})
        return self.ingest_document(document)

    def query(self, request: QueryInput) -> dict[str, Any]:
        kb_id = self.kb_name(request.course_id, request.kb_id)
        info = self.adapter.get_knowledge_base(kb_id)
        if info is None:
            raise DeepTutorError("kb_not_found", "Knowledge base was not found.", status_code=404)
        if not self._ready(info):
            raise DeepTutorError("kb_not_ready", "Knowledge base is not ready.", status_code=409)
        result = self.adapter.search(kb_id, request.question.strip())
        return {"course_id": request.course_id, "kb_id": kb_id, "result": result}
