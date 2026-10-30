import os
import re
from typing import Any, Protocol

import httpx


class DeepTutorAPIClient(Protocol):
    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]: ...
    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]: ...
    def check_readiness(self) -> dict[str, Any]: ...


class MockDeepTutorClient:
    def check_readiness(self) -> dict[str, Any]:
        return {"status": "ready", "components": {
            "deeptutor": "available", "course_kb": "available",
            "ollama": "available", "moodle": "configured",
        }}

    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]:
        return {"document_id": str(resource_id), "course_id": str(course_id_moodle), "kb_id": kb_name or "mock-kb", "action": "add", "status": "ready", "metadata": {}}

    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]:
        return {"status": "success", "answer": "Mock grounded answer.", "course_id": course_id, "kb_name": kb_name or "mock-kb", "sources": [{"title": "mock.pdf", "page": 1, "score": 1.0}], "ai": {"provider": "mock", "model": "mock", "fallback_used": False}}


class RealDeepTutorClient:
    def __init__(self, base_url: str, service_token: str | None = None, personal_token: str | None = None):
        self.base_url = base_url.rstrip("/")
        self._personal_token = personal_token
        self.service_token = service_token if service_token is not None else os.getenv("LMS_MOODLE_DISCOVERY_TOKEN")

    def request(self, method: str, path: str, payload=None, timeout_seconds: float = 180) -> dict[str, Any]:
        from urllib.parse import urlsplit
        try:
            origin=urlsplit(self.base_url)
            origin.port
        except ValueError:
            raise BackendRequestError(503) from None
        if (not self._personal_token or origin.scheme not in {"http","https"} or not origin.hostname
            or origin.username or origin.password or origin.query or origin.fragment
            or not path.startswith("/") or path.startswith("//")):
            raise BackendRequestError(401 if not self._personal_token else 503)
        try:
            response=httpx.request(method,self.base_url+path,json=payload,
                headers={"Authorization":"Bearer "+self._personal_token},timeout=timeout_seconds,follow_redirects=False)
            if response.status_code!=200:
                code=None
                safe_details={}
                try:
                    detail=response.json().get("detail",{})
                    candidate=detail.get("code") if isinstance(detail,dict) else None
                    if isinstance(candidate,str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}",candidate): code=candidate
                    if isinstance(detail,dict):
                        for key in ("requested_count","validated_count"):
                            value=detail.get(key)
                            if type(value) is int and value >= 0: safe_details[key]=value
                except (ValueError,TypeError): pass
                raise BackendRequestError(response.status_code if response.status_code in (401,403,404,409,413,422,502,503,504) else 503,code,safe_details)
            result=response.json()
            if not isinstance(result,dict): raise BackendRequestError(502)
            return result
        except BackendRequestError: raise
        except httpx.TimeoutException: raise BackendRequestError(504,"CLIENT_TIMEOUT") from None
        except (httpx.HTTPError,ValueError): raise BackendRequestError(503) from None

    def identity(self): return self.request("GET","/auth/me")

    def ingest_resource(self, course_id_moodle: int, resource_id: int, kb_name: str | None = None) -> dict[str, Any]:
        headers = {"X-Internal-Api-Key": self.service_token} if self.service_token else None
        response = httpx.post(f"{self.base_url}/moodle/resources/ingest", json={"course_id_moodle": course_id_moodle, "resource_id": resource_id, "kb_name": kb_name}, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def check_readiness(self) -> dict[str, Any]:
        try:
            response = httpx.get(f"{self.base_url}/health/ready", timeout=10)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise RuntimeError("DeepTutor readiness is unavailable.") from exc
        if not isinstance(data, dict) or data.get("status") not in {"ready", "degraded"}:
            raise RuntimeError("DeepTutor readiness is unavailable.")
        return data

    def chat(self, question: str, course_id: str, kb_name: str | None = None) -> dict[str, Any]:
        response = httpx.post(f"{self.base_url}/chat/grounded", json={"question": question, "course_id": course_id, "kb_name": kb_name},
                              headers={"Authorization":"Bearer "+self._personal_token} if self._personal_token else None, timeout=120)
        response.raise_for_status()
        return response.json()


def create_deeptutor_client() -> DeepTutorAPIClient:
    use_mock = os.getenv("USE_MOCK_API", "false").strip().lower() in {"1", "true", "yes"}
    if use_mock:
        return MockDeepTutorClient()
    return RealDeepTutorClient(os.getenv("DEEPTUTOR_API_BASE_URL", "http://127.0.0.1:8000"))


class BackendRequestError(RuntimeError):
    def __init__(self,status_code,code=None,details=None):
        self.status_code,self.code=status_code,code
        self.details=details if isinstance(details,dict) else {}
        super().__init__(f"Backend request failed ({status_code}).")
