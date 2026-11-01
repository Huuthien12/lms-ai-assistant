"""UI identity and courses from the same dependency as guarded query/chat."""
from dataclasses import asdict
from fastapi import APIRouter, Depends, HTTPException
from deeptutor_integration.auth_contracts import CourseAction


def create_identity_router(authorizer):
    router = APIRouter(tags=["verified-identity"])

    @router.get("/auth/me")
    def identity(access=Depends(authorizer)):
        courses=[]
        for course in access.courses():
            scope=access.scope(course["id"])
            can_sync=False
            if access.boundary.capability_evidence is not None:
                try: access.scope(course["id"],action=CourseAction.SYNC_COURSE_RESOURCE); can_sync=True
                except HTTPException: pass
            courses.append({**asdict(scope),"can_sync":can_sync})
        return {"owner_ref":access.owner_ref,"moodle_user_id":access.binding.moodle_user_id,"courses":courses}

    @router.get("/auth/me/profile")
    def profile(access=Depends(authorizer)):
        """Expose only the authenticated user's stable, read-only Moodle identity."""
        return {"moodle_user_id":access.binding.moodle_user_id,
                "course_count":len(access.courses()),"account_status":"VERIFIED"}

    return router
