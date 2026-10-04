from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .contracts import NormalizedDocument, SourceDocument
from .errors import DeepTutorError


@dataclass(frozen=True)
class DocumentFormat:
    extension: str
    mime_types: frozenset[str]


DOCUMENT_FORMATS = {
    ".pdf": DocumentFormat(".pdf", frozenset({"application/pdf"})),
    ".docx": DocumentFormat(
        ".docx",
        frozenset({"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}),
    ),
    ".pptx": DocumentFormat(
        ".pptx",
        frozenset({"application/vnd.openxmlformats-officedocument.presentationml.presentation"}),
    ),
    ".ppt": DocumentFormat(
        ".ppt", frozenset({"application/vnd.ms-powerpoint", "application/mspowerpoint"}),
    ),
    ".md": DocumentFormat(".md", frozenset({"text/markdown", "text/x-markdown", "text/plain"})),
}


def source_sha256(content: bytes) -> str:
    if not content:
        raise DeepTutorError("invalid_document", "Document content must be non-empty.", status_code=422)
    return sha256(content).hexdigest()


def validate_document_format(source: SourceDocument) -> DocumentFormat:
    extension = Path(source.filename).suffix.lower()
    document_format = DOCUMENT_FORMATS.get(extension)
    if document_format is None:
        raise DeepTutorError("unsupported_document", "Document type is not supported.", status_code=415)
    if source.mime_type.lower().split(";", 1)[0].strip() not in document_format.mime_types:
        raise DeepTutorError("document_format_mismatch", "Document type does not match its declared format.", status_code=415)
    return document_format


class DocumentNormalizer:
    """Normalize supported LMS source documents without touching the filesystem."""

    def normalize(self, source: SourceDocument) -> NormalizedDocument:
        document_format = validate_document_format(source)
        digest = source_sha256(source.content)
        if document_format.extension != ".md":
            raise DeepTutorError(
                "normalizer_unavailable",
                "A normalizer for this document type is not available yet.",
                status_code=501,
            )
        try:
            markdown = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DeepTutorError("invalid_document", "Markdown content must be valid UTF-8.", status_code=422) from exc
        markdown = markdown.replace("\r\n", "\n").replace("\r", "\n")
        if not markdown.strip():
            raise DeepTutorError("invalid_document", "Markdown content must not be blank.", status_code=422)
        return NormalizedDocument(
            document_id=source.document_id,
            course_id=source.course_id,
            original_filename=source.filename,
            original_mime_type=source.mime_type,
            source=source.source,
            metadata=source.metadata,
            sha256=digest,
            markdown=markdown,
            normalizer_version="markdown-v1",
        )
