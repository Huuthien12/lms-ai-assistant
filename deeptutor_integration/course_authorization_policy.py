"""Fail-closed, route-independent Moodle course authorization policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from deeptutor_integration.auth_contracts import (
    AuthContractError,
    AuthorizationDecision,
    AuthorizationNotConfiguredError,
    CacheState,
    CourseAccessDeniedError,
    CourseAction,
    MoodleAuthorizationUnavailableError,
    MoodleBindingDeniedError,
    MoodleBindingResolver,
    MoodleUserBinding,
    PrincipalRequiredError,
    VerifiedPrincipal,
    VerifiedPrincipalResolver,
    require_dependency,
)


class BoundCourseAuthorizer(Protocol):
    """Trusted dependency that authorizes one bound Moodle user and action."""

    def __call__(
        self,
        binding: MoodleUserBinding,
        course_id: int,
        action: CourseAction,
    ) -> AuthorizationDecision: ...


class QueryAuthorizationCachePolicy(Protocol):
    """Explicit server-side policy required before a cached query is accepted."""

    def __call__(self, decision: AuthorizationDecision) -> bool: ...


def _nonempty_namespace(namespace: str) -> None:
    if not isinstance(namespace, str) or not namespace.strip():
        raise ValueError("moodle_namespace must be a non-empty string")


@dataclass(frozen=True)
class CourseAuthorizationPolicy:
    """Coordinates injected trust decisions without performing I/O itself."""

    moodle_namespace: str
    principal_resolver: VerifiedPrincipalResolver | None
    binding_resolver: MoodleBindingResolver | None
    course_authorizer: BoundCourseAuthorizer | None
    query_cache_policy: QueryAuthorizationCachePolicy | None = None

    def __post_init__(self) -> None:
        _nonempty_namespace(self.moodle_namespace)

    def authorize(
        self,
        request: Any,
        course_id: int,
        action: CourseAction,
        *,
        now: datetime | None = None,
    ) -> AuthorizationDecision:
        """Return only an exact LIVE allow decision, otherwise fail closed."""
        self._validate_request(course_id, action)
        principal = self._resolve_principal(request, now)
        binding = self._resolve_binding(principal)
        decision = self._resolve_decision(binding, course_id, action)
        self._validate_decision(decision, course_id, action)
        return decision

    def _validate_request(self, course_id: int, action: CourseAction) -> None:
        if type(course_id) is not int or course_id <= 0:
            raise CourseAccessDeniedError()
        if not isinstance(action, CourseAction):
            raise CourseAccessDeniedError()

    def _resolve_principal(self, request: Any, now: datetime | None) -> VerifiedPrincipal:
        resolver = require_dependency(self.principal_resolver)
        failure: type[AuthContractError] | None = None
        try:
            principal = resolver(request)
            if not isinstance(principal, VerifiedPrincipal):
                raise PrincipalRequiredError()
            principal.require_active(now)
            return principal
        except PrincipalRequiredError:
            failure = PrincipalRequiredError
        except AuthContractError:
            failure = MoodleAuthorizationUnavailableError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        # Raise after leaving the exception handler so no dependency exception
        # remains as __cause__ or __context__ on the public error.
        raise failure()

    def _resolve_binding(self, principal: VerifiedPrincipal) -> MoodleUserBinding:
        resolver = require_dependency(self.binding_resolver)
        failure: type[AuthContractError] | None = None
        try:
            binding = resolver(principal)
            if not isinstance(binding, MoodleUserBinding):
                raise MoodleBindingDeniedError()
            binding.require_active()
            if (
                binding.issuer != principal.issuer
                or binding.subject != principal.subject
                or binding.moodle_namespace != self.moodle_namespace
            ):
                raise MoodleBindingDeniedError()
            return binding
        except MoodleAuthorizationUnavailableError:
            failure = MoodleAuthorizationUnavailableError
        except MoodleBindingDeniedError:
            failure = MoodleBindingDeniedError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()

    def _resolve_decision(
        self,
        binding: MoodleUserBinding,
        course_id: int,
        action: CourseAction,
    ) -> AuthorizationDecision:
        authorizer = require_dependency(self.course_authorizer)
        failure: type[AuthContractError] | None = None
        try:
            decision = authorizer(binding, course_id, action)
            if not isinstance(decision, AuthorizationDecision):
                raise CourseAccessDeniedError()
            return decision
        except MoodleAuthorizationUnavailableError:
            failure = MoodleAuthorizationUnavailableError
        except CourseAccessDeniedError:
            failure = CourseAccessDeniedError
        except AuthContractError:
            failure = MoodleAuthorizationUnavailableError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()

    def _validate_decision(
        self,
        decision: AuthorizationDecision,
        course_id: int,
        action: CourseAction,
    ) -> None:
        if not decision.allowed or decision.moodle_course_id != course_id or decision.action is not action:
            raise CourseAccessDeniedError()
        if decision.cache_state is CacheState.LIVE:
            return
        if action is CourseAction.SYNC_COURSE_RESOURCE:
            raise CourseAccessDeniedError()
        if (
            action is not CourseAction.QUERY_COURSE
            or decision.cache_state is not CacheState.FRESH_CACHE
            or self.query_cache_policy is None
        ):
            raise CourseAccessDeniedError()
        cache_failure = False
        try:
            accepted = self.query_cache_policy(decision)
        except Exception:
            cache_failure = True
        if cache_failure:
            raise MoodleAuthorizationUnavailableError()
        if accepted is not True:
            raise CourseAccessDeniedError()
