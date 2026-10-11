"""Application publication and ACTIVE-only retrieval over the existing engine."""
from contextlib import contextmanager
from hashlib import sha256
from uuid import uuid4
from pathlib import Path
from .contracts import DocumentInput
from .errors import DeepTutorError
from .full_source_adapter import DeepTutorFullSourceAdapter
from .moodle_ingestion_ledger import MoodleIngestionLedgerV2, LedgerV2Record, LedgerV2Lifecycle, ChunkManifestEntry
from .provenance_contracts import canonical_chunk_sha256, canonical_source_ref
from .verified_context import active_records, verify_raw_chunks, build_context
from .service import DeepTutorService


class VerifiedPublicationService:
    def __init__(self, config, adapter=None):
        self.config=config
        runtime=config.runtime_dir.resolve()
        if not runtime.is_relative_to(config.repository_root.resolve()):
            raise DeepTutorError("invalid_document","Publication runtime must be inside the workspace.",status_code=422)
        self.ledger=MoodleIngestionLedgerV2(runtime)
        self.publication_lock=MoodleIngestionLedgerV2(runtime / "publication-lock")
        self.adapter=adapter or DeepTutorFullSourceAdapter(config)
        self.materializer=DeepTutorService(config)

    def publish(self, scope, document):
        if document.course_id.strip().lower()!=scope.course_key.lower():
            raise DeepTutorError("course_access_denied","Document does not belong to the authorized course.",status_code=403)
        artifact=sha256(document.markdown.encode("utf-8")).hexdigest()
        if document.artifact_sha256 is not None and document.artifact_sha256!=artifact:
            raise DeepTutorError("invalid_document","Document artifact hash is invalid.",status_code=422)
        with self.publication_lock._locked():
            state=self.ledger.snapshot()
            existing=next((r for r in active_records(state,scope) if r.document_id==document.document_id
                           and r.source_sha256==document.sha256 and r.artifact_sha256==artifact
                           and r.normalizer_version==document.normalizer_version),None)
            if existing: return {"document_id":document.document_id,"document_version_id":existing.document_version_id,
                                 "kb_id":scope.kb_name,"status":"ACTIVE","action":"deduplicated"}
            version=uuid4().hex
            physical="vl-"+version
            record=LedgerV2Record(source_namespace=scope.source_namespace,moodle_course_id=scope.moodle_course_id,
                course_id=scope.course_key,kb_id=scope.kb_name,document_id=document.document_id,
                document_version_id=version,source_sha256=document.sha256,artifact_sha256=artifact,
                original_filename=document.original_filename,normalizer_version=document.normalizer_version,
                index_provider="llamaindex",index_version="unpublished",lifecycle=LedgerV2Lifecycle.PENDING,
                created_at=self.ledger._now())
            self.ledger.create_pending(record)
            try:
                path=self.materializer._document_path(DocumentInput(course_id=scope.course_key,
                    document_id=document.document_id,filename=version+".md",content=document.markdown))
                result=self.adapter.publish(physical,path)
                if (not isinstance(result,dict) or result.get("provider")!="llamaindex"
                    or result.get("publication_ref")!=physical or not isinstance(result.get("index_version"),str)
                    or not result["index_version"].strip() or not isinstance(result.get("chunks"),list)):
                    raise DeepTutorError("invalid_publication","Full-source publication evidence is invalid.",status_code=502)
                manifest=tuple(ChunkManifestEntry(chunk_id=c["chunk_id"],
                    source_ref=canonical_source_ref(scope.kb_name,version,c["chunk_id"]),
                    content_sha256=canonical_chunk_sha256(c["content"])) for c in result["chunks"])
                self.ledger.publish_replacement(record,physical,manifest,index_version=result["index_version"])
            except Exception as error:
                self.ledger.mark_failed(record,"publication_failed")
                if isinstance(error,DeepTutorError): raise
                raise DeepTutorError("invalid_publication","Full-source publication could not be completed.",status_code=502) from None
        return {"document_id":document.document_id,"document_version_id":version,
                "kb_id":scope.kb_name,"status":"ACTIVE","action":"published"}

    def delete(self, scope, document_id):
        with self.publication_lock._locked():
            count=self.ledger.delete_document(scope.source_namespace,scope.course_key,scope.kb_name,document_id)
        return {"document_id":document_id,"status":"DELETED","retired_versions":count}

    def documents(self, scope):
        return [{"document_id":r.document_id,"document_version_id":r.document_version_id,
                 "filename":r.original_filename,"status":"ACTIVE","source_sha256":r.source_sha256}
                for r in active_records(self.ledger.snapshot(),scope)]

    @contextmanager
    def context(self, scope, question):
        # Hold the existing OS ledger lock through the consumer's provider call.
        # Successful update/delete cannot retire a source while a prompt uses it.
        with self.ledger._locked():
            records=active_records(self.ledger._state(),scope)
            chunks=[]
            for record in records:
                raw=self.adapter.retrieve(record.provider_publication_ref,question)
                chunks.extend(verify_raw_chunks(record,scope,raw))
            yield build_context(scope,question,chunks)

    def revalidate(self, context):
        records=active_records(self.ledger._state(),context.scope)
        for chunk in context.chunks:
            matching=[r for r in records if r.document_id==chunk.document_id
                      and r.document_version_id==chunk.document_version_id and r.source_sha256==chunk.source_sha256
                      and r.artifact_sha256==chunk.artifact_sha256 and r.index_version==chunk.index_version
                      and r.provider_publication_ref==chunk.publication_ref
                      and any(c.chunk_id==chunk.chunk_id and c.source_ref==chunk.source_ref
                              and c.content_sha256==canonical_chunk_sha256(chunk.content) for c in r.chunk_manifest)]
            if len(matching)!=1:
                raise DeepTutorError("inactive_context","Learning context is no longer active.",status_code=409)
