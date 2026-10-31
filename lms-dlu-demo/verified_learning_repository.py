"""Additive SQL context/owner bindings around the existing learning repositories."""
from dataclasses import asdict
import json
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from deeptutor_integration.contracts import AuthorizedCourseScope
from deeptutor_integration.verified_context import VerifiedChunk, VerifiedRetrievalContext


class VerifiedLearningRepository:
    def __init__(self, connect, quizzes, evidence):
        self.connect,self.quizzes,self.evidence=connect,quizzes,evidence

    def ensure_schema(self):
        with self.connect() as conn:
            conn.cursor().execute("""
                IF OBJECT_ID('dbo.VerifiedLearningArtifacts', 'U') IS NULL
                CREATE TABLE dbo.VerifiedLearningArtifacts (
                    artifact_type NVARCHAR(32) NOT NULL,
                    artifact_id NVARCHAR(64) NOT NULL,
                    owner_ref NVARCHAR(128) NOT NULL,
                    course_id NVARCHAR(128) NOT NULL,
                    payload_json NVARCHAR(MAX) NOT NULL,
                    created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
                    CONSTRAINT PK_VerifiedLearningArtifacts PRIMARY KEY (artifact_type, artifact_id)
                );
                IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id=OBJECT_ID(N'dbo.VerifiedLearningArtifacts')
                    AND name=N'IX_VerifiedLearningArtifacts_OwnerCourse')
                CREATE INDEX IX_VerifiedLearningArtifacts_OwnerCourse ON dbo.VerifiedLearningArtifacts(owner_ref,course_id,artifact_type);
                IF OBJECT_ID('dbo.ReviewBatches', 'U') IS NULL
                CREATE TABLE dbo.ReviewBatches (
                    batch_id NVARCHAR(64) NOT NULL PRIMARY KEY,
                    attempt_id NVARCHAR(64) NOT NULL UNIQUE REFERENCES dbo.QuizAttempts(attempt_id),
                    owner_ref NVARCHAR(128) NOT NULL,
                    course_id NVARCHAR(128) NOT NULL,
                    status NVARCHAR(16) NOT NULL CHECK (status IN ('PENDING','READY','FAILED')),
                    lease_id NVARCHAR(64) NULL,
                    provenance_json NVARCHAR(MAX) NOT NULL,
                    created_at DATETIME2 NOT NULL,
                    updated_at DATETIME2 NOT NULL
                );
                IF OBJECT_ID('dbo.ReviewBatchCards', 'U') IS NULL
                CREATE TABLE dbo.ReviewBatchCards (
                    batch_id NVARCHAR(64) NOT NULL REFERENCES dbo.ReviewBatches(batch_id),
                    flashcard_id NVARCHAR(64) NOT NULL REFERENCES dbo.Flashcards(flashcard_id),
                    chapter_id NVARCHAR(128) NOT NULL,
                    CONSTRAINT PK_ReviewBatchCards PRIMARY KEY (batch_id,flashcard_id)
                );
            """)
            conn.commit()

    def put(self, kind, identifier, scope, payload):
        self.put_many(kind,[(identifier,payload)],scope)

    def put_many(self, kind, items, scope):
        encoded=[(identifier,json.dumps(payload,ensure_ascii=False,allow_nan=False))
                 for identifier,payload in items]
        if not encoded: raise ValueError("persistence_failure")
        with self.connect() as conn:
            try:
                cursor=conn.cursor()
                for identifier,payload in encoded:
                    cursor.execute("INSERT INTO dbo.VerifiedLearningArtifacts (artifact_type,artifact_id,owner_ref,course_id,payload_json) VALUES (?,?,?,?,?)",
                        kind,identifier,scope.owner_ref,scope.course_key,payload)
                conn.commit()
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

    def reserve_review_batch(self, attempt_id, scope, provenance):
        """Short transaction; AI work is deliberately outside this reservation."""
        now=datetime.now(timezone.utc).replace(tzinfo=None); lease_id=uuid4().hex
        with self.connect() as conn:
            try:
                cursor=conn.cursor(); cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                row=cursor.execute("SELECT batch_id,owner_ref,course_id,status,updated_at FROM dbo.ReviewBatches WITH (UPDLOCK,HOLDLOCK) WHERE attempt_id=?",attempt_id).fetchone()
                if row is not None:
                    if row[1]!=scope.owner_ref or row[2]!=scope.course_key: raise ValueError("learning_scope_forbidden")
                    if row[3]=="READY": conn.commit(); return {"batch_id":row[0],"status":"READY"}
                    if row[3]=="PENDING" and row[4] and row[4] > now-timedelta(minutes=5):
                        conn.commit(); return {"batch_id":row[0],"status":"PENDING"}
                    cursor.execute("UPDATE dbo.ReviewBatches SET status='PENDING',lease_id=?,updated_at=? WHERE batch_id=?",lease_id,now,row[0])
                    conn.commit(); return {"batch_id":row[0],"status":"PENDING","lease_id":lease_id}
                batch_id=uuid4().hex
                cursor.execute("INSERT INTO dbo.ReviewBatches (batch_id,attempt_id,owner_ref,course_id,status,lease_id,provenance_json,created_at,updated_at) VALUES (?,?,?,?, 'PENDING',?,?,?,?)",batch_id,attempt_id,scope.owner_ref,scope.course_key,lease_id,json.dumps(provenance),now,now)
                conn.commit(); return {"batch_id":batch_id,"status":"PENDING","lease_id":lease_id}
            except ValueError:
                conn.rollback(); raise
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

    def publish_review_batch(self, batch_id, lease_id, scope, cards, chapter_by_card, artifact_payloads):
        """One SQL transaction publishes cards, bindings, mappings, and READY state."""
        if not cards or len({card.flashcard_id for card in cards})!=len(cards): raise ValueError("invalid_flashcard")
        now=datetime.now(timezone.utc).replace(tzinfo=None)
        with self.connect() as conn:
            try:
                cursor=conn.cursor(); cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                batch=cursor.execute("SELECT owner_ref,course_id,status,lease_id FROM dbo.ReviewBatches WITH (UPDLOCK,HOLDLOCK) WHERE batch_id=?",batch_id).fetchone()
                if batch is None: raise ValueError("review_batch_not_found")
                if batch[0]!=scope.owner_ref or batch[1]!=scope.course_key: raise ValueError("learning_scope_forbidden")
                if batch[2]=="READY": conn.commit(); return {"batch_id":batch_id,"status":"READY"}
                if batch[2]!="PENDING" or batch[3]!=lease_id: raise ValueError("review_batch_lease_lost")
                for card in cards:
                    card.learning_context.scope.require(scope.owner_ref,scope.course_key)
                    artifact=card.model_dump_json()
                    cursor.execute("INSERT INTO dbo.Flashcards (flashcard_id,course_id,topic,created_at,artifact_json) VALUES (?,?,?,?,?)",card.flashcard_id,scope.course_key,card.topic,now,artifact)
                    cursor.execute("INSERT INTO dbo.VerifiedLearningArtifacts (artifact_type,artifact_id,owner_ref,course_id,payload_json) VALUES ('flashcard',?,?,?,?)",card.flashcard_id,scope.owner_ref,scope.course_key,json.dumps(artifact_payloads[card.flashcard_id],ensure_ascii=False,allow_nan=False))
                    cursor.execute("INSERT INTO dbo.ReviewBatchCards (batch_id,flashcard_id,chapter_id) VALUES (?,?,?)",batch_id,card.flashcard_id,chapter_by_card[card.flashcard_id])
                cursor.execute("UPDATE dbo.ReviewBatches SET status='READY',lease_id=NULL,updated_at=? WHERE batch_id=? AND lease_id=?",now,batch_id,lease_id)
                if cursor.rowcount!=1: raise ValueError("review_batch_lease_lost")
                conn.commit(); return {"batch_id":batch_id,"status":"READY"}
            except ValueError:
                conn.rollback(); raise
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

    def fail_review_batch(self, batch_id, lease_id, scope):
        """Release a failed generation for immediate trusted retry without publishing cards."""
        with self.connect() as conn:
            try:
                cursor=conn.cursor(); cursor.execute("SET XACT_ABORT ON; SET TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
                cursor.execute("UPDATE dbo.ReviewBatches SET status='FAILED',lease_id=NULL,updated_at=? WHERE batch_id=? AND owner_ref=? AND course_id=? AND status='PENDING' AND lease_id=?",datetime.now(timezone.utc).replace(tzinfo=None),batch_id,scope.owner_ref,scope.course_key,lease_id)
                conn.commit()
            except Exception:
                conn.rollback()

    def get(self, kind, identifier):
        with self.connect() as conn:
            row=conn.cursor().execute("SELECT owner_ref,course_id,payload_json FROM dbo.VerifiedLearningArtifacts WHERE artifact_type=? AND artifact_id=?",kind,identifier).fetchone()
        if row is None: raise ValueError("artifact_not_found")
        return {"owner_ref":row[0],"course_id":row[1],"payload":json.loads(row[2])}

    def list(self, kind, scope):
        with self.connect() as conn:
            rows=conn.cursor().execute("SELECT TOP (50) artifact_id,payload_json FROM dbo.VerifiedLearningArtifacts WHERE artifact_type=? AND owner_ref=? AND course_id=? ORDER BY created_at DESC,artifact_id DESC",
                                      kind,scope.owner_ref,scope.course_key).fetchall()
        return [{"artifact_id":r[0],"payload":json.loads(r[1])} for r in reversed(rows)]

    def clear_history(self, scope):
        with self.connect() as conn:
            conn.cursor().execute("DELETE FROM dbo.VerifiedLearningArtifacts WHERE artifact_type='chat' AND owner_ref=? AND course_id=?",scope.owner_ref,scope.course_key)
            conn.commit()

    def attempt(self, identifier):
        with self.connect() as conn:
            row=conn.cursor().execute("SELECT quiz_id,student_id,course_id,status FROM dbo.QuizAttempts WHERE attempt_id=?",identifier).fetchone()
        if row is None: raise ValueError("attempt_not_found")
        return {"quiz_id":row[0],"owner_ref":row[1],"course_id":row[2],"status":row[3]}

    def answers(self, identifier):
        with self.connect() as conn:
            rows=conn.cursor().execute("SELECT question_id,selected_option_id,correct FROM dbo.QuizAnswers WHERE attempt_id=?",identifier).fetchall()
        return [{"question_id":r[0],"selected_option_id":r[1],"correct":bool(r[2])} for r in rows]


def context_payload(context): return asdict(context)


def restore_context(payload):
    return VerifiedRetrievalContext(AuthorizedCourseScope(**payload["scope"]),payload["question"],
        tuple(VerifiedChunk(**c) for c in payload["chunks"]),payload["context_id"])
