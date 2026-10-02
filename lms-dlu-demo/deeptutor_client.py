from typing import Any, Protocol
import httpx

# 1. Định nghĩa Interface chuẩn
class DeepTutorAPIClient(Protocol):
    def ingest_resource(self, course_id: int, resource_id: int, kb_name: str) -> dict[str, Any]:
        ...

    def chat(self, query: str, kb_name: str, session_id: str = "default") -> dict[str, Any]:
        ...

# 2. Mock Client dùng cho hiện tại (bỏ qua lỗi 503)
class MockDeepTutorClient:
    def ingest_resource(self, course_id: int, resource_id: int, kb_name: str) -> dict[str, Any]:
        print(f"[MOCK API] Nhận yêu cầu Ingest: Course {course_id}, Resource {resource_id} -> KB {kb_name}")
        return {
            "status": "success",
            "message": "Mock ingestion successful",
            "kb_name": kb_name
        }

    def chat(self, query: str, kb_name: str, session_id: str = "default") -> dict[str, Any]:
        print(f"[MOCK API] Nhận yêu cầu Chat: '{query}' (KB: {kb_name})")
        return {
            "answer": "Đây là câu trả lời giả lập từ Mock Client. Giao diện LMS sẽ hiển thị text này bình thường.",
            "sources": [
                {"file": "Chuong 1.pdf", "page": 3, "content": "Nội dung trích xuất giả lập để test UI."}
            ]
        }

# 3. Real Client dùng cho sau này (gọi API FastAPI thật)
class RealDeepTutorClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url

    def ingest_resource(self, course_id: int, resource_id: int, kb_name: str) -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}/moodle/resources/ingest",
            json={
                "course_id_moodle": course_id,
                "resource_id": resource_id,
                "kb_name": kb_name
            }
        )
        response.raise_for_status()
        return response.json()

    def chat(self, query: str, kb_name: str, session_id: str = "default") -> dict[str, Any]:
        response = httpx.post(
            f"{self.base_url}/chat/grounded",
            json={
                "query": query,
                "kb_name": kb_name,
                "session_id": session_id
            }
        )
        response.raise_for_status()
        return response.json()