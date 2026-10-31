"""DB-API contract fake; reuses existing Quan lifecycle/evidence cursor fixtures."""
from datetime import datetime
from test_quiz_lifecycle import MemoryConnection, MemoryCursor, EvidenceCursor, Row


class LearningConnection(MemoryConnection):
    def cursor(self): return LearningCursor(self)


class LearningCursor(MemoryCursor):
    def execute(self, sql, *values):
        statement=" ".join(sql.split()); s=self.conn.state
        if "ReviewBatches" in statement:
            s.setdefault("batches",{})
            if statement.startswith("SELECT batch_id,owner_ref"):
                found=next(((batch,row) for batch,row in s["batches"].items() if row[0]==values[0]),None)
                self.result=Row((found[0],found[1][1],found[1][2],found[1][3],found[1][6])) if found else None
            elif statement.startswith("SELECT owner_ref,course_id,status,lease_id"):
                row=s["batches"].get(values[0]); self.result=Row((row[1],row[2],row[3],row[4])) if row else None
            elif statement.startswith("INSERT INTO"):
                batch,attempt,owner,course,lease,provenance,created,updated=values
                if any(row[0]==attempt for row in s["batches"].values()): raise RuntimeError("duplicate attempt")
                s["batches"][batch]=(attempt,owner,course,"PENDING",lease,provenance,datetime.utcnow())
            elif statement.startswith("UPDATE"):
                if "status='FAILED'" in statement:
                    _,batch,owner,course,lease=values; old=s["batches"][batch]
                    self.rowcount=int(old[1:3]==(owner,course) and old[3]=="PENDING" and old[4]==lease)
                    if self.rowcount: s["batches"][batch]=(old[0],old[1],old[2],"FAILED",None,old[5],datetime.utcnow())
                elif "status='PENDING'" in statement:
                    lease,_,batch=values; old=s["batches"][batch]; s["batches"][batch]=(old[0],old[1],old[2],"PENDING",lease,old[5],datetime.utcnow())
                elif "status='READY'" in statement:
                    _,batch,lease=values; old=s["batches"][batch]; self.rowcount=int(old[4]==lease); s["batches"][batch]=(old[0],old[1],old[2],"READY",None,old[5],datetime.utcnow())
        elif "ReviewBatchCards" in statement:
            s.setdefault("batch_cards",set())
            if statement.startswith("INSERT INTO"):
                membership=(values[0],values[1])
                if any(item[:2]==membership for item in s["batch_cards"]): raise RuntimeError("duplicate membership")
                s["batch_cards"].add((*membership,values[2]))
        elif "VerifiedLearningArtifacts" in statement:
            if statement.startswith("INSERT INTO"):
                if "VALUES ('flashcard'" in statement:
                    kind="flashcard"; identifier,owner,course,payload=values
                else:
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
