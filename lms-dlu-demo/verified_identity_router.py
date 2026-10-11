"""UI identity and courses from the same dependency as guarded query/chat."""
from dataclasses import asdict
from fastapi import APIRouter, Depends


def create_identity_router(authorizer):
    router = APIRouter(tags=["verified-identity"])

    @router.get("/auth/me")
    def identity(access=Depends(authorizer)):
        return {"owner_ref": access.owner_ref,
                "moodle_user_id": access.binding.moodle_user_id,
                "courses": [asdict(access.scope(course["id"])) for course in access.courses()]}

    return router
