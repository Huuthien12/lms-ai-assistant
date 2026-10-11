from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from deeptutor_client import DeepTutorAPIClient, create_deeptutor_client
from moodle_service_auth import require_moodle_service

router = APIRouter(tags=["lms-chat-ui"])

class MoodleIngestionRequest(BaseModel):
    course_id_moodle: int = Field(gt=0)
    resource_id: int = Field(gt=0)
    kb_name: str | None = Field(default=None, min_length=1, max_length=120)


def get_client() -> DeepTutorAPIClient:
    return create_deeptutor_client()


@router.get("/lms/ready")
def lms_readiness(client: DeepTutorAPIClient = Depends(get_client)):
    try:
        return client.check_readiness()
    except Exception as exc:
        raise HTTPException(503, detail={"code": "deeptutor_unavailable", "message": "DeepTutor is unavailable."}) from exc


@router.post("/lms/resources/ingest", dependencies=[Depends(require_moodle_service)])
def lms_ingest_resource(request: MoodleIngestionRequest, client: DeepTutorAPIClient = Depends(get_client)):
    try:
        return client.ingest_resource(request.course_id_moodle, request.resource_id, request.kb_name)
    except Exception as exc:
        raise HTTPException(502, detail={"code": "deeptutor_unavailable", "message": "DeepTutor is unavailable."}) from exc
