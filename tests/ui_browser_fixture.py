"""Loopback-only fixture API for visual Streamlit checks; never import in production."""
from fastapi import FastAPI, Header, HTTPException


app = FastAPI(title="DeepTutor UI browser fixture")


def fixture_identity(authorization: str | None) -> dict:
    if authorization not in {"Bearer A", "Bearer empty", "Bearer error", "Bearer staff"}:
        raise HTTPException(status_code=401, detail={"code": "unauthorized"})
    return {
        "owner_ref": "fixture-owner-not-for-display",
        "moodle_user_id": "fixture-user-not-for-display",
        "courses": [{"course_key": "INT1339", "course_name": "Lập trình Python", "can_sync": authorization == "Bearer staff"}],
    }


@app.get("/auth/me")
def identity(authorization: str | None = Header(default=None)):
    return fixture_identity(authorization)


@app.get("/auth/me/profile")
def profile(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"moodle_user_id": "fixture-user-not-for-display", "course_count": 1, "account_status": "VERIFIED"}


@app.get("/learning/courses/INT1339/overview")
def overview(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"course_id": "INT1339", "active_publication_count": 0 if authorization == "Bearer empty" else 1,
            "can_manage_documents": authorization == "Bearer staff"}


@app.get("/learning/courses/INT1339/documents")
def documents(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    if authorization == "Bearer error":
        raise HTTPException(status_code=503, detail={"code": "publication_unavailable"})
    if authorization == "Bearer empty":
        return {"resources": [], "publications": []}
    return {"resources": [], "publications": [{
        "document_id": "fixture-python-basics", "filename": "Python cơ bản.pdf", "status": "ACTIVE",
        "mime_type": "application/pdf",
    }]}


@app.get("/learning/courses/INT1339/history")
def history(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"history": []}


@app.get("/learning/courses/INT1339/resources")
def resources(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"resources": [{
        "document_id": "fixture-python-basics", "filename": "Python cơ bản.pdf", "mime_type": "application/pdf",
    }]}


@app.post("/learning/courses/INT1339/chat")
def chat(_: dict, authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"status": "success", "answer": "Python là ngôn ngữ lập trình đa dụng.", "context_id": "fixture-context", "sources": [{"title": "Python cơ bản.pdf", "document_id": "fixture-python-basics", "verification_status": "VERIFIED_ACTIVE"}]}


@app.post("/learning/courses/INT1339/quizzes")
def quiz(_: dict, authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"quiz_id": "fixture-quiz", "scope_mode": "chapter", "sources": [{"title": "Python cơ bản.pdf", "document_id": "fixture-python-basics"}], "questions": [{
        "question_id": "fixture-question", "question": "Python là gì?",
        "options": [{"id": "a", "text": "Ngôn ngữ lập trình"}, {"id": "b", "text": "Hệ điều hành"}, {"id": "c", "text": "Trình duyệt"}, {"id": "d", "text": "Cơ sở dữ liệu"}],
    }]}


@app.post("/learning/quizzes/fixture-quiz/attempts")
def start_attempt(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"attempt_id": "fixture-attempt"}


@app.post("/learning/attempts/fixture-attempt/submit")
def submit(_: dict, authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"attempt_id": "fixture-attempt", "score_percent": 0, "correct_count": 0, "total_questions": 1}


@app.get("/learning/attempts/fixture-attempt/review")
def review(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"results": [{"question_id": "fixture-question", "selected_option_id": "b", "correct": False, "correct_answer": "Ngôn ngữ lập trình", "explanation": "Theo tài liệu Python cơ bản.", "explanation_status": "available", "sources": [{"title": "Python cơ bản.pdf", "document_id": "fixture-python-basics"}]}]}


@app.post("/learning/attempts/fixture-attempt/review-flashcards")
def review_flashcards(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"batch_id": "fixture-batch", "status": "READY"}


@app.post("/learning/courses/INT1339/flashcards")
def create_flashcards(_: dict, authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"created_count": 1, "flashcards": []}


@app.get("/learning/courses/INT1339/flashcards")
def flashcards(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    if authorization == "Bearer empty":
        return {"flashcards": []}
    return {"flashcards": [{"flashcard_id": "fixture-card", "front_text": "Python dùng để làm gì?", "back_text": "Xây dựng phần mềm và tự động hóa.", "reviewed": False, "needs_review": True, "sources": [{"title": "Python cơ bản.pdf", "document_id": "fixture-python-basics"}]}]}


@app.post("/learning/flashcards/fixture-card/reviews")
def record_review(_: dict, authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    return {"status": "recorded"}


@app.get("/learning/courses/INT1339/progress")
def progress(authorization: str | None = Header(default=None)):
    fixture_identity(authorization)
    if authorization == "Bearer empty":
        return {"topics": [], "recommendations": []}
    return {"topics": [{"topic": "Python cơ bản", "mastery_score": 40, "level": "DEVELOPING", "confidence": "MEDIUM", "evidence_count": 2, "last_updated_at": "2026-11-01T04:00:00Z"}], "recommendations": [{"topic": "Python cơ bản", "recommended_actions": ["REVIEW_TOPIC", "GENERATE_FLASHCARDS"], "reason": "Ôn lại nội dung nền tảng trước Quiz tiếp theo."}]}
