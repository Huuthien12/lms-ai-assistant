"""Server-created integration contracts, never HTTP request bodies or auth policy.

The application must verify principal/enrollment, resolve the canonical course/KB,
and validate retrieval before constructing these values. Shape validation here
does not establish authorization or verify document provenance.
"""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal


class LearningScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    owner_id: str = Field(min_length=1, max_length=128, pattern=r"\S")
    course_id: str = Field(min_length=1, max_length=128, pattern=r"\S")

    def require(self, owner_id: str, course_id: str) -> None:
        if self.owner_id != owner_id or self.course_id != course_id:
            raise ValueError("learning_scope_forbidden")


class LearningSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    source_id: str = Field(min_length=1, pattern=r"\S")
    chunk_id: str | None = None
    document_id: str | None = None
    version: str | None = None
    content_hash: str | None = None
    provenance_status: Literal["unverified", "verified"] = "unverified"


class VerifiedLearningContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    scope: LearningScope
    kb_id: str = Field(min_length=1, pattern=r"\S")
    retrieval_id: str = Field(min_length=1, pattern=r"\S")
    text: str = Field(min_length=1, max_length=200000, pattern=r"\S")
    sources: tuple[LearningSource, ...] = ()

    @model_validator(mode="after")
    def unique_sources(self):
        keys = [(source.source_id, source.chunk_id) for source in self.sources]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate context source")
        return self

    def source_metadata(self) -> list[dict]:
        return [source.model_dump(exclude_none=True) for source in self.sources]
