from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_PRIVATE_METADATA_MARKERS = ("token", "auth", "url", "password", "secret", "path")


def _safe_metadata(value: dict[str, Any]) -> dict[str, Any]:
    """Drop transport and credential fields before they enter document contracts."""
    safe: dict[str, Any] = {}
    for key, item in value.items():
        if any(marker in str(key).lower() for marker in _PRIVATE_METADATA_MARKERS):
            continue
        if isinstance(item, dict):
            safe[str(key)] = _safe_metadata(item)
        elif isinstance(item, list):
            safe[str(key)] = [
                _safe_metadata(entry) if isinstance(entry, dict) else entry for entry in item
            ]
        else:
            safe[str(key)] = item
    return safe


class _SourceMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def sanitize_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _safe_metadata(value)


class SourceDocument(_SourceMetadata):
    """Original LMS bytes plus sanitized, transport-independent provenance."""

    document_id: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=200)
    source: str = Field(default="unknown", min_length=1, max_length=120)
    content: bytes = Field(min_length=1)

    @model_validator(mode="after")
    def filename_is_basename(self) -> "SourceDocument":
        if Path(self.filename).name != self.filename:
            raise ValueError("filename must not contain a directory path")
        return self


class NormalizedDocument(_SourceMetadata):
    """Normalized Markdown ready to become a ``DocumentInput`` in a later task."""

    document_id: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=120)
    original_filename: str = Field(min_length=1, max_length=255)
    original_mime_type: str = Field(min_length=1, max_length=200)
    source: str = Field(default="unknown", min_length=1, max_length=120)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    markdown: str = Field(min_length=1)
    normalizer_version: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def original_filename_is_basename(self) -> "NormalizedDocument":
        if Path(self.original_filename).name != self.original_filename:
            raise ValueError("original_filename must not contain a directory path")
        return self


class DocumentInput(BaseModel):
    document_id: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=120)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str | None = Field(default=None, max_length=200)
    source: str = Field(default="unknown", min_length=1, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: str | None = None
    path: str | None = None
    kb_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def require_one_payload(self) -> "DocumentInput":
        if bool(self.content) == bool(self.path):
            raise ValueError("exactly one of content or path is required")
        if Path(self.filename).name != self.filename:
            raise ValueError("filename must not contain a directory path")
        return self


class KnowledgeBaseInput(BaseModel):
    course_id: str = Field(min_length=1, max_length=120)
    document: DocumentInput
    kb_id: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def course_must_match(self) -> "KnowledgeBaseInput":
        if self.document.course_id != self.course_id:
            raise ValueError("document course_id must match knowledge-base course_id")
        return self


class QueryInput(BaseModel):
    course_id: str = Field(min_length=1, max_length=120)
    question: str = Field(min_length=1, max_length=8000)
    kb_id: str | None = Field(default=None, min_length=1, max_length=120)


class IntegrationResponse(BaseModel):
    success: bool
    data: dict[str, Any] | list[Any] | None = None
    error: dict[str, Any] | None = None
