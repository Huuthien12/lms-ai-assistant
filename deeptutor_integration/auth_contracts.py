"""Backend-neutral authentication and Moodle course-authorization contracts.

These types deliberately contain no credential verification, request parsing, or
Moodle calls.  Production composition must inject fail-closed implementations.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol, TypeVar


class CourseAction(StrEnum):
    """Actions whose course access is evaluated independently."""

    QUERY_COURSE = "QUERY_COURSE"
    SYNC_COURSE_RESOURCE = "SYNC_COURSE_RESOURCE"


class CacheState(StrEnum):
    """Provenance of an authorization decision."""

    LIVE = "LIVE"
    FRESH_CACHE = "FRESH_CACHE"


class AuthContractError(Exception):
    """Safe, public contract error; never populate it with credential data."""

    code = "authorization_not_configured"
    status_code = 503
    public_message = "Authorization is not configured."

    def __init__(self) -> None:
        super().__init__(self.public_message)

    def public_payload(self) -> dict[str, str]:
        return {"code": self.code, "message": self.public_message}


class PrincipalRequiredError(AuthContractError):
    code = "principal_required"
    status_code = 401
    public_message = "A verified principal is required."


class MoodleBindingDeniedError(AuthContractError):
    code = "moodle_binding_denied"
    status_code = 403
    public_message = "Moodle identity binding is not permitted."


class CourseAccessDeniedError(AuthContractError):
    code = "course_access_denied"
    status_code = 403
    public_message = "Course access is not permitted."


class MoodleAuthorizationUnavailableError(AuthContractError):
    code = "moodle_authorization_unavailable"
    status_code = 503
    public_message = "Moodle authorization is unavailable."


class AuthorizationNotConfiguredError(AuthContractError):
    code = "authorization_not_configured"
    status_code = 503
    public_message = "Authorization is not configured."


def _require_nonempty(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _require_aware_timestamp(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware datetime")


def _require_positive_int(value: int, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class VerifiedPrincipal:
    subject: str
    issuer: str
    authenticated_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_nonempty(self.subject, "subject")
        _require_nonempty(self.issuer, "issuer")
        _require_aware_timestamp(self.authenticated_at, "authenticated_at")
        _require_aware_timestamp(self.expires_at, "expires_at")
        if self.expires_at <= self.authenticated_at:
            raise ValueError("expires_at must be after authenticated_at")

    def require_active(self, now: datetime | None = None) -> None:
        moment = now or datetime.now(timezone.utc)
        _require_aware_timestamp(moment, "now")
        if moment >= self.expires_at:
            raise PrincipalRequiredError()


@dataclass(frozen=True)
class MoodleUserBinding:
    issuer: str
    subject: str
    moodle_namespace: str
    moodle_user_id: int
    binding_version: int
    active: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.issuer, "issuer")
        _require_nonempty(self.subject, "subject")
        _require_nonempty(self.moodle_namespace, "moodle_namespace")
        _require_positive_int(self.moodle_user_id, "moodle_user_id")
        _require_positive_int(self.binding_version, "binding_version")
        if type(self.active) is not bool:
            raise ValueError("active must be a boolean")

    def require_active(self) -> None:
        if not self.active:
            raise MoodleBindingDeniedError()


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason_code: str
    moodle_course_id: int
    action: CourseAction
    decided_at: datetime
    policy_version: str
    cache_state: CacheState

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise ValueError("allowed must be a boolean")
        _require_nonempty(self.reason_code, "reason_code")
        _require_positive_int(self.moodle_course_id, "moodle_course_id")
        if not isinstance(self.action, CourseAction):
            raise ValueError("action must be a CourseAction")
        _require_aware_timestamp(self.decided_at, "decided_at")
        _require_nonempty(self.policy_version, "policy_version")
        if not isinstance(self.cache_state, CacheState):
            raise ValueError("cache_state must be a CacheState")


class VerifiedPrincipalResolver(Protocol):
    def __call__(self, request: Any) -> VerifiedPrincipal: ...


class MoodleBindingResolver(Protocol):
    def __call__(self, principal: VerifiedPrincipal) -> MoodleUserBinding: ...


class CourseAuthorizer(Protocol):
    def __call__(
        self,
        principal: VerifiedPrincipal,
        course_id: int,
        action: CourseAction,
    ) -> AuthorizationDecision: ...


DependencyT = TypeVar("DependencyT")


def require_dependency(dependency: DependencyT | None) -> DependencyT:
    """Fail closed when application composition has not supplied a dependency."""
    if dependency is None:
        raise AuthorizationNotConfiguredError()
    return dependency
