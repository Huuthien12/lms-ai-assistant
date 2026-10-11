"""Additive SQL context/owner bindings around the existing learning repositories."""
from dataclasses import asdict
import json
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
            """)
            conn.commit()

    def put(self, kind, identifier, scope, payload):
        encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False)
        with self.connect() as conn:
            try:
                conn.cursor().execute("INSERT INTO dbo.VerifiedLearningArtifacts (artifact_type,artifact_id,owner_ref,course_id,payload_json) VALUES (?,?,?,?,?)",
                    kind,identifier,scope.owner_ref,scope.course_key,encoded)
                conn.commit()
            except Exception:
                conn.rollback(); raise ValueError("persistence_failure") from None

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
