from fastapi import APIRouter
from pydantic import BaseModel
from deeptutor_client import DeepTutorAPIClient, MockDeepTutorClient, RealDeepTutorClient
# Cấu hình dùng Mock tạm thời
USE_MOCK_API = True
api_client: DeepTutorAPIClient = MockDeepTutorClient() if USE_MOCK_API else RealDeepTutorClient()

router = APIRouter(tags=["lms-chat-ui"])

class ChatRequest(BaseModel):
    query: str
    kb_name: str
    session_id: str = "default"

@router.post("/lms/chat")
def lms_student_chat(request: ChatRequest):
    # Gọi hàm chat qua interface chung
    result = api_client.chat(
        query=request.query,
        kb_name=request.kb_name,
        session_id=request.session_id
    )
    return result