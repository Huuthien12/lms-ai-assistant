"""Transport-neutral shared authorization adapter for future query routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from deeptutor_integration.auth_contracts import (
    AuthContractError,
    AuthorizationDecision,
    AuthorizationNotConfiguredError,
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
from deeptutor_integration.course_authorization_policy import CourseAuthorizationPolicy


def _nonempty(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True)
class CanonicalCourseScope:
    """Server-owned course and knowledge-base mapping, never client authority."""

    moodle_namespace: str
    moodle_course_id: int
    canonical_course_key: str
    kb_id: str
    scope_version: str

    def __post_init__(self) -> None:
        _nonempty(self.moodle_namespace, "moodle_namespace")
        if type(self.moodle_course_id) is not int or self.moodle_course_id <= 0:
            raise ValueError("moodle_course_id must be a positive integer")
        _nonempty(self.canonical_course_key, "canonical_course_key")
        _nonempty(self.kb_id, "kb_id")
        _nonempty(self.scope_version, "scope_version")


class CanonicalCourseScopeResolver(Protocol):
    def __call__(self, selector: object) -> CanonicalCourseScope: ...


@dataclass(frozen=True)
class AuthorizedQueryContext:
    principal: VerifiedPrincipal
    binding: MoodleUserBinding
    scope: CanonicalCourseScope
    decision: AuthorizationDecision


@dataclass(frozen=True)
class SharedQueryAuthorizationAdapter:
    """Composes one consistent trust chain before query or grounded-chat work."""

    principal_resolver: VerifiedPrincipalResolver | None
    binding_resolver: MoodleBindingResolver | None
    scope_resolver: CanonicalCourseScopeResolver | None
    policy: CourseAuthorizationPolicy | None

    def authorize(
        self,
        request: Any,
        course_selector: object,
        *,
        requested_kb_id: str | None = None,
        now: datetime | None = None,
    ) -> AuthorizedQueryContext:
        policy = self._aligned_policy()
        principal = self._resolve_principal(request, now)
        binding = self._resolve_binding(principal)
        scope = self._resolve_scope(course_selector)
        if binding.moodle_namespace != scope.moodle_namespace or policy.moodle_namespace != scope.moodle_namespace:
            raise CourseAccessDeniedError()
        if requested_kb_id is not None and requested_kb_id != scope.kb_id:
            raise CourseAccessDeniedError()
        decision = self._authorize_with_policy(policy, request, scope.moodle_course_id, now)
        return AuthorizedQueryContext(principal, binding, scope, decision)

    def reauthorize(
        self,
        request: Any,
        previous: AuthorizedQueryContext,
        *,
        now: datetime | None = None,
    ) -> AuthorizedQueryContext:
        """Freshly resolve every authority and reject changed binding/scope state."""
        if not isinstance(previous, AuthorizedQueryContext):
            raise CourseAccessDeniedError()
        current = self.authorize(
            request,
            previous.scope.canonical_course_key,
            requested_kb_id=previous.scope.kb_id,
            now=now,
        )
        if (
            current.binding.binding_version != previous.binding.binding_version
            or current.scope.scope_version != previous.scope.scope_version
            or current.scope.moodle_course_id != previous.scope.moodle_course_id
            or current.scope.kb_id != previous.scope.kb_id
        ):
            raise CourseAccessDeniedError()
        return current

    def _aligned_policy(self) -> CourseAuthorizationPolicy:
        policy = require_dependency(self.policy)
        if not isinstance(policy, CourseAuthorizationPolicy):
            raise AuthorizationNotConfiguredError()
        if (
            policy.principal_resolver is not self.principal_resolver
            or policy.binding_resolver is not self.binding_resolver
        ):
            raise AuthorizationNotConfiguredError()
        return policy

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
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()

    def _resolve_binding(self, principal: VerifiedPrincipal) -> MoodleUserBinding:
        resolver = require_dependency(self.binding_resolver)
        failure: type[AuthContractError] | None = None
        try:
            binding = resolver(principal)
            if not isinstance(binding, MoodleUserBinding):
                raise MoodleBindingDeniedError()
            binding.require_active()
            if binding.issuer != principal.issuer or binding.subject != principal.subject:
                raise MoodleBindingDeniedError()
            return binding
        except MoodleBindingDeniedError:
            failure = MoodleBindingDeniedError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()

    def _resolve_scope(self, selector: object) -> CanonicalCourseScope:
        resolver = require_dependency(self.scope_resolver)
        failure: type[AuthContractError] | None = None
        try:
            scope = resolver(selector)
            if not isinstance(scope, CanonicalCourseScope):
                raise MoodleAuthorizationUnavailableError()
            return scope
        except CourseAccessDeniedError:
            failure = CourseAccessDeniedError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()

    def _authorize_with_policy(
        self,
        policy: CourseAuthorizationPolicy,
        request: Any,
        course_id: int,
        now: datetime | None,
    ) -> AuthorizationDecision:
        failure: type[AuthContractError] | None = None
        try:
            return policy.authorize(request, course_id, CourseAction.QUERY_COURSE, now=now)
        except PrincipalRequiredError:
            failure = PrincipalRequiredError
        except MoodleBindingDeniedError:
            failure = MoodleBindingDeniedError
        except CourseAccessDeniedError:
            failure = CourseAccessDeniedError
        except AuthorizationNotConfiguredError:
            failure = AuthorizationNotConfiguredError
        except Exception:
            failure = MoodleAuthorizationUnavailableError
        raise failure()
