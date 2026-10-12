"""Tho source signals into the sole Thiện publication authority."""
from dataclasses import asdict
from .moodle_trust import source_version,lifecycle_signals,MoodleSourceVersion
from .document_normalizer import DocumentNormalizer
from .moodle_ingestion_ledger import MoodleIngestionLedgerV2
from .verified_context import active_records
from .auth_contracts import CourseAction
from .errors import DeepTutorError


class MoodlePublicationAdapter:
    def __init__(self,publications):
        self.publications=publications
        self.normalizer=DocumentNormalizer()
        self.scan_lock=MoodleIngestionLedgerV2(publications.config.runtime_dir/"moodle-scan-lock")

    @staticmethod
    def resources(access,course):
        context,items=access.boundary.discover(access._token,course)
        access.project(context)
        return [{"document_id":r.document_id,"resource_id":r.resource_id,"filename":r.filename,"mime_type":r.mime_type} for r in items]

    def sync(self,access,course):
        with self.scan_lock._locked():
            scope=access.scope(course,action=CourseAction.SYNC_COURSE_RESOURCE)
            context,documents=access.boundary.scan_course(access._token,scope.moodle_course_id)
            if access.project(context)!=scope: raise DeepTutorError("source_scope_mismatch","Course scope changed.",status_code=403)
            # Complete scan/download AND normalization precede any destructive signal.
            normalized={d.document_id:self.normalizer.normalize(d) for d in documents}
            current=[source_version(d) for d in documents]
            records=active_records(self.publications.ledger.snapshot(),scope)
            previous=[MoodleSourceVersion(scope.source_namespace,scope.moodle_course_id,r.document_id,r.source_sha256,r.original_filename or "Document",r.source_version_hint) for r in records]
            signals=lifecycle_signals(previous,current,moodle_namespace=scope.source_namespace,course_id=scope.moodle_course_id)
            results=[]
            for signal in signals:
                if signal.kind!="TOMBSTONE":
                    access.reauthorize(scope,CourseAction.SYNC_COURSE_RESOURCE)
                    results.append(self.publications.publish(scope,normalized[signal.document_id]))
            # A failed candidate returns before tombstones; previous ACTIVE is retained.
            for signal in signals:
                if signal.kind=="TOMBSTONE":
                    access.reauthorize(scope,CourseAction.SYNC_COURSE_RESOURCE)
                    results.append(self.publications.delete(scope,signal.document_id))
            return {"course_id":scope.course_key,"signals":[asdict(s) for s in signals],"publications":results}

    def sync_document(self,access,course,identifier):
        with self.scan_lock._locked():
            scope=access.scope(course,action=CourseAction.SYNC_COURSE_RESOURCE)
            context,resources=access.boundary.discover(access._token,scope.moodle_course_id)
            if access.project(context)!=scope: raise DeepTutorError("source_scope_mismatch","Course scope changed.",status_code=403)
            matches=[r for r in resources if r.document_id==identifier or str(r.resource_id)==identifier]
            if len(matches)!=1: raise DeepTutorError("document_not_found","Select an exact Moodle document identity.",status_code=404)
            document=access.boundary.download(access._token,scope.moodle_course_id,matches[0].document_id)
            normalized=self.normalizer.normalize(document)
            access.reauthorize(scope,CourseAction.SYNC_COURSE_RESOURCE)
            return self.publications.publish(scope,normalized)
