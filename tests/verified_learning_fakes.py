"""DB-API contract fake; reuses existing Quan lifecycle/evidence cursor fixtures."""
from test_quiz_lifecycle import MemoryConnection, MemoryCursor, EvidenceCursor, Row


class LearningConnection(MemoryConnection):
    def cursor(self): return LearningCursor(self)


class LearningCursor(MemoryCursor):
    def execute(self, sql, *values):
        statement=" ".join(sql.split()); s=self.conn.state
        if "VerifiedLearningArtifacts" in statement:
            if statement.startswith("INSERT INTO"):
                kind,identifier,owner,course,payload=values
                if (kind,identifier) in s["bindings"]: raise RuntimeError("duplicate artifact")
                s["bindings"][(kind,identifier)]=(owner,course,payload)
            elif statement.startswith("SELECT owner_ref"):
                row=s["bindings"].get(tuple(values)); self.result=Row(row) if row else None
            elif statement.startswith("SELECT TOP"):
                kind,owner,course=values
                self.result=[Row((identifier,row[2])) for (k,identifier),row in s["bindings"].items() if k==kind and row[:2]==(owner,course)]
            elif statement.startswith("DELETE"):
                owner,course=values
                s["bindings"]={key:row for key,row in s["bindings"].items() if not (key[0]=="chat" and row[:2]==(owner,course))}
        elif statement.startswith("SELECT quiz_id,student_id"):
            a=s["attempts"].get(values[0]); self.result=Row((a["quiz_id"],a["student_id"],a["course_id"],a["status"])) if a else None
        elif statement.startswith("SELECT question_id,selected_option_id"):
            self.result=[Row((question,selected,correct)) for (attempt,question),(selected,correct) in s["answers"].items() if attempt==values[0]]
        elif any(table in statement for table in ("dbo.Flashcards","dbo.FlashcardReviews","dbo.LearningEvents","dbo.TopicMastery")):
            EvidenceCursor.execute(self,statement,*values)
        else:
            MemoryCursor.execute(self,statement,*values)
            if statement.startswith("SELECT quiz_id, status") and self.result is not None:
                a=s["attempts"][values[0]]
                self.result=Row((a["quiz_id"],a["status"],a["student_id"],a["course_id"]))
        return self
    def fetchall(self): return self.result or []
