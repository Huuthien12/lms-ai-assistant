"""Adapter hooks for the shared principal/course guard owned by integration.

No role, header or client student_id is interpreted as authority here. Inject a
FastAPI dependency returning LearningScope after shared policy verification.
"""
from fastapi import HTTPException

from backend.services.ai.learning_context import LearningScope


def learning_auth_unavailable() -> LearningScope:
    raise HTTPException(503, detail={
        "code": "learning_auth_not_configured",
        "message": "Verified learning authorization is not configured.",
    })


def require_scope(scope: LearningScope, owner_id: str, course_id: str) -> None:
    if not isinstance(scope, LearningScope):
        learning_auth_unavailable()
    try:
        scope.require(owner_id, course_id)
    except ValueError:
        raise HTTPException(403, detail={"code": "learning_scope_forbidden",
                                        "message": "Learning resource access denied."}) from None
