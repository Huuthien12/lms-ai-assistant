"""Live Moodle credentials/enrollment adapted to the shared course policy."""
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from deeptutor_integration.api import QueryAccessChecker
from deeptutor_integration.auth_contracts import (
    AuthContractError, AuthorizationDecision, AuthorizationNotConfiguredError,
    CacheState, CourseAccessDeniedError, CourseAction,
    MoodleAuthorizationUnavailableError, MoodleUserBinding,
    PrincipalRequiredError, VerifiedPrincipal,
)
from deeptutor_integration.course_authorization_policy import CourseAuthorizationPolicy
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.service import DeepTutorService


def _reject(error: AuthContractError) -> None:
    raise HTTPException(error.status_code, detail=error.public_payload()) from None


def _moodle_call(base_url: str, token: str, function: str, **parameters):
    failed = False
    try:
        response = httpx.post(
            f"{base_url}/webservice/rest/server.php",
            data={"wstoken": token, "wsfunction": function,
                  "moodlewsrestformat": "json", **parameters},
            timeout=15, follow_redirects=False,
        )
    except (httpx.HTTPError, httpx.InvalidURL):
        failed = True
    if failed:
        _reject(MoodleAuthorizationUnavailableError())
    if response.status_code in (401, 403):
        _reject(PrincipalRequiredError())
    if response.status_code != 200:
        _reject(MoodleAuthorizationUnavailableError())
    invalid = False
    try:
        data = response.json()
    except ValueError:
        invalid = True
    if invalid:
        _reject(MoodleAuthorizationUnavailableError())
    if isinstance(data, dict) and ("exception" in data or "errorcode" in data):
        if data.get("errorcode") in ("invalidtoken", "invalidsecret", "invaliduser"):
            _reject(PrincipalRequiredError())
        _reject(MoodleAuthorizationUnavailableError())
    return data


@dataclass(frozen=True)
class AuthorizedCourseScope:
    moodle_course_id: int
    course_key: str
    kb_name: str
    owner_ref: str
    source_namespace: str


@dataclass
class MoodleQueryAccess:
    """Request-local evidence, shared by login, query and learning HTTP guards."""
    service: DeepTutorService = field(repr=False)
    request: Request = field(repr=False)
    principal: VerifiedPrincipal
    binding: MoodleUserBinding
    _token: str = field(repr=False)
    action_authorizer: Any = field(default=None, repr=False)
    _enrollments: list | None = field(default=None, repr=False)

    @property
    def owner_ref(self) -> str:
        return sha256((self.principal.issuer + "\0" + self.principal.subject).encode()).hexdigest()

    def courses(self) -> list[dict]:
        self.principal.require_active()
        if self._enrollments is None:
            courses = _moodle_call(self.binding.moodle_namespace, self._token,
                                   "core_enrol_get_users_courses",
                                   userid=self.binding.moodle_user_id, returnusercount=0)
            if not isinstance(courses, list) or any(
                not isinstance(c, dict) or type(c.get("id")) is not int or c["id"] <= 0
                or not isinstance(c.get("shortname"), str) or not c["shortname"].strip()
                for c in courses
            ):
                _reject(MoodleAuthorizationUnavailableError())
            self._enrollments = courses
        return self._enrollments

    def scope(self, course_id: str | int, kb_name: str | None = None,
              action: CourseAction = CourseAction.QUERY_COURSE) -> AuthorizedCourseScope:
        matches = [c for c in self.courses() if (
            c["id"] == course_id if type(course_id) is int
            else c["shortname"].strip().lower() == str(course_id).strip().lower()
        )]
        if not matches:
            _reject(CourseAccessDeniedError())
        if len(matches) != 1:
            _reject(MoodleAuthorizationUnavailableError())
        course = matches[0]
        # One Moodle ID and one application alias must identify the same enrollment.
        if sum(c["id"] == course["id"] for c in self.courses()) != 1:
            _reject(MoodleAuthorizationUnavailableError())
        if sum(c["shortname"].strip().lower() == course["shortname"].strip().lower()
               for c in self.courses()) != 1:
            _reject(MoodleAuthorizationUnavailableError())

        def decision(binding, course_id, requested_action):
            if requested_action is not CourseAction.QUERY_COURSE:
                if self.action_authorizer is None:
                    raise AuthorizationNotConfiguredError()
                return self.action_authorizer(binding, course_id, requested_action)
            allowed = binding == self.binding and course_id == course["id"]
            return AuthorizationDecision(allowed, "active_enrollment" if allowed else "course_access_denied",
                course_id, requested_action, datetime.now(timezone.utc), "moodle-active-enrollment/v1", CacheState.LIVE)

        policy = CourseAuthorizationPolicy(self.binding.moodle_namespace,
            lambda _: self.principal, lambda _: self.binding, decision)
        try:
            policy.authorize(self.request, course["id"], action)
            canonical = course["shortname"].strip()
            kb = self.service.kb_name(canonical, kb_name)
        except AuthContractError as error:
            _reject(error)
        except DeepTutorError as error:
            raise HTTPException(error.status_code, detail=error.as_dict()) from None
        return AuthorizedCourseScope(course["id"], canonical, kb, self.owner_ref, self.binding.moodle_namespace)

    def require_owner(self, owner_ref: str) -> None:
        if owner_ref != self.owner_ref:
            _reject(CourseAccessDeniedError())

    def moodle_adapter(self):
        # Reuse Tho's secure-download/resource adapter with this verified user's credential.
        from moodle_adapter import MoodleAdapter
        return MoodleAdapter(self.binding.moodle_namespace, self._token)

    def __call__(self, query) -> None:
        scope = self.scope(query.course_id, query.kb_id)
        query.course_id, query.kb_id = scope.course_key, scope.kb_name
        self.request.state.authorized_scope = scope


def create_moodle_query_authorizer(service: DeepTutorService, base_url: str | None,
                                   action_authorizer=None):
    namespace = (base_url or "").rstrip("/")

    def require_course_query(request: Request) -> QueryAccessChecker:
        credentials = request.headers.get("Authorization", "").split()
        if len(credentials) != 2 or credentials[0].lower() != "bearer":
            _reject(PrincipalRequiredError())
        token = credentials[1]
        try:
            origin = urlsplit(namespace)
            configured = (origin.scheme in {"http", "https"} and bool(origin.hostname)
                          and origin.username is None and origin.password is None
                          and not origin.query and not origin.fragment)
            origin.port
        except ValueError:
            configured = False
        if not configured:
            _reject(AuthorizationNotConfiguredError())
        identity = _moodle_call(namespace, token, "core_webservice_get_site_info")
        user_id = identity.get("userid") if isinstance(identity, dict) else None
        if type(user_id) is not int or user_id <= 0:
            _reject(MoodleAuthorizationUnavailableError())
        now = datetime.now(timezone.utc)
        principal = VerifiedPrincipal(str(user_id), namespace, now, now + timedelta(minutes=1))
        binding = MoodleUserBinding(namespace, principal.subject, namespace, user_id, 1, True)
        access = MoodleQueryAccess(service, request, principal, binding, token, action_authorizer)
        request.state.moodle_access = access
        return access

    return require_course_query
