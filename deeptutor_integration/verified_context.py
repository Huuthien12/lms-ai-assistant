"""One application trust model for chat, quiz and flashcards."""
from dataclasses import dataclass
from hashlib import sha256
import math
from uuid import uuid4
from .contracts import AuthorizedCourseScope
from .errors import DeepTutorError
from .moodle_ingestion_ledger import LedgerV2Lifecycle
from .provenance_contracts import canonical_chunk_sha256, canonical_source_ref


@dataclass(frozen=True)
class VerifiedChunk:
    document_id: str
    document_version_id: str
    source_sha256: str
    artifact_sha256: str
    chunk_id: str
    source_ref: str
    content_sha256: str
    content: str
    filename: str
    publication_ref: str
    index_version: str
    score: float | None = None
    page: str | int | None = None

    def citation(self):
        return {"source_id":self.source_ref,"source_ref":self.source_ref,"document_id":self.document_id,
                "document_version_id":self.document_version_id,"source_sha256":self.source_sha256,
                "artifact_sha256":self.artifact_sha256,"chunk_id":self.chunk_id,
                "content_sha256":self.content_sha256,"title":self.filename,
                "publication_ref":self.publication_ref,"index_version":self.index_version,
                "verification_status":"VERIFIED_ACTIVE","score":self.score,"page":self.page,
                "preview":self.content[:400]}


@dataclass(frozen=True)
class VerifiedRetrievalContext:
    scope: AuthorizedCourseScope
    question: str
    chunks: tuple[VerifiedChunk,...]
    context_id: str

    def text(self):
        return "\n\n".join(f"[{c.source_ref}]\n{c.content}" for c in self.chunks)

    def citations(self): return [c.citation() for c in self.chunks]


def active_records(state, scope):
    return [r for r in state.records.values() if r.lifecycle is LedgerV2Lifecycle.ACTIVE
            and r.source_namespace==scope.source_namespace and r.moodle_course_id==scope.moodle_course_id
            and r.course_id==scope.course_key and r.kb_id==scope.kb_name]


def verify_raw_chunks(record, scope, raw):
    if record not in active_records(type("Snapshot",(),{"records":{"r":record}})(),scope):
        raise DeepTutorError("inactive_publication","Publication is not active for this course.",status_code=409)
    if not isinstance(raw,dict) or raw.get("provider")!=record.index_provider or raw.get("index_version")!=record.index_version or raw.get("publication_ref")!=record.provider_publication_ref or not isinstance(raw.get("chunks"),list):
        raise DeepTutorError("invalid_raw_retrieval","Raw retrieval evidence is invalid.",status_code=502)
    verified=[]; seen=set()
    for candidate in raw["chunks"]:
        if not isinstance(candidate,dict) or not isinstance(candidate.get("chunk_id"),str):
            raise DeepTutorError("invalid_raw_retrieval","Raw retrieval evidence is invalid.",status_code=502)
        identifier=candidate["chunk_id"]
        try:
            digest=canonical_chunk_sha256(candidate.get("content"))
            reference=canonical_source_ref(scope.kb_name,record.document_version_id,identifier)
        except DeepTutorError:
            raise DeepTutorError("invalid_raw_retrieval","Raw retrieval evidence is invalid.",status_code=502) from None
        evidence=[c for c in record.chunk_manifest if c.chunk_id==identifier and c.source_ref==reference and c.content_sha256==digest]
        if len(evidence)!=1 or identifier in seen:
            raise DeepTutorError("unverified_chunk","Chunk does not match the active publication.",status_code=409)
        seen.add(identifier)
        score=candidate.get("score"); page=candidate.get("page")
        if score is not None and (type(score) not in (int,float) or not math.isfinite(score)):
            raise DeepTutorError("invalid_raw_retrieval","Retrieval score is invalid.",status_code=502)
        if page is not None and type(page) not in (str,int): page=None
        verified.append(VerifiedChunk(record.document_id,record.document_version_id,record.source_sha256,
            record.artifact_sha256,identifier,reference,digest,candidate["content"],record.original_filename or "Document",
            record.provider_publication_ref,record.index_version,score,page))
    return verified


def build_context(scope, question, chunks, max_characters=32000):
    # Select whole, already-verified chunks. UI previews never become generation text.
    selected=[]; used=0
    for chunk in chunks:
        size=len(chunk.content)+len(chunk.source_ref)+4
        if used+size<=max_characters: selected.append(chunk); used+=size
    return VerifiedRetrievalContext(scope,question,tuple(selected),uuid4().hex)
