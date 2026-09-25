from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator


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
