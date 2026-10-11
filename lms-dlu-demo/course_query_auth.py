"""Live Moodle credentials/enrollment adapted to the shared course policy."""
from datetime import datetime, timedelta, timezone
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


def create_moodle_query_authorizer(service: DeepTutorService, base_url: str | None):
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

        def authorize_query(query):
            # This endpoint returns only active enrollments accessible to the token's user.
            courses = _moodle_call(namespace, token, "core_enrol_get_users_courses",
                                   userid=user_id, returnusercount=0)
            if not isinstance(courses, list) or any(
                not isinstance(course, dict) or type(course.get("id")) is not int
                or course["id"] <= 0 or not isinstance(course.get("shortname"), str)
                or not course["shortname"].strip() for course in courses
            ):
                _reject(MoodleAuthorizationUnavailableError())
            matches = [course for course in courses
                       if course["shortname"].strip().lower() == query.course_id.strip().lower()]
            if not matches:
                _reject(CourseAccessDeniedError())
            if len(matches) != 1:
                _reject(MoodleAuthorizationUnavailableError())
            course = matches[0]
            canonical_key = course["shortname"].strip()
            try:
                kb_id = service.kb_name(canonical_key, query.kb_id)
            except DeepTutorError as error:
                raise HTTPException(error.status_code, detail=error.as_dict()) from None

            def enrolled_decision(bound_user, course_id, action):
                allowed = (bound_user == binding and course_id == course["id"]
                           and action is CourseAction.QUERY_COURSE)
                return AuthorizationDecision(
                    allowed, "active_enrollment" if allowed else "course_access_denied",
                    course_id, action, datetime.now(timezone.utc), "moodle-active-enrollment/v1",
                    CacheState.LIVE,
                )

            policy = CourseAuthorizationPolicy(
                namespace, lambda _: principal, lambda _: binding, enrolled_decision,
            )
            try:
                policy.authorize(request, course["id"], CourseAction.QUERY_COURSE)
            except AuthContractError as error:
                _reject(error)
            # Retrieval uses the same server-resolved course and KB that were authorized.
            query.course_id, query.kb_id = canonical_key, kb_id

        return authorize_query

    return require_course_query
