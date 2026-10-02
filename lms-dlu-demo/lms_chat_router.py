from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor_client import DeepTutorAPIClient, create_deeptutor_client

router = APIRouter(tags=["lms-chat-ui"])

class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    course_id: str = Field(min_length=1)
    kb_name: str | None = None


def get_client() -> DeepTutorAPIClient:
    return create_deeptutor_client()

@router.post("/lms/chat")
def lms_student_chat(request: ChatRequest, client: DeepTutorAPIClient = Depends(get_client)):
    try:
        return client.chat(request.question, request.course_id, request.kb_name)
    except Exception as exc:
        raise HTTPException(502, detail={"code": "deeptutor_unavailable", "message": "DeepTutor is unavailable."}) from exc
