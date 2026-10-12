"""Request-scoped Moodle identity, course authority and source lifecycle boundary.

No personal token is stored in a principal, binding, scope, resource, or event.
Callers supply it for every authorization; the service never caches a decision.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol, Callable
from urllib.parse import urlsplit

import requests

from .auth_contracts import (
    AuthorizationDecision,
    CacheState,
    CourseAccessDeniedError,
    CourseAction,
    MoodleAuthorizationUnavailableError,
    MoodleUserBinding,
    PrincipalRequiredError,
    VerifiedPrincipal,
)
from .contracts import SourceDocument
from .course_authorization_policy import CourseAuthorizationPolicy
from .shared_query_authorization import CanonicalCourseScope


def _positive_id(value: object) -> int:
    if type(value) is int and value > 0:
        return value
    raise MoodleAuthorizationUnavailableError()


def _origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or
                parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError
        return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == "https" else 80)
    except (TypeError, ValueError):
        raise ValueError("Moodle URL is not configured safely.") from None


def personal_bearer_token(authorization: str | None) -> str:
    """Extract only an original personal Moodle Bearer credential."""
    if not isinstance(authorization, str):
        raise PrincipalRequiredError()
    parts = authorization.split(" ")
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1] or any(c.isspace() for c in parts[1]):
        raise PrincipalRequiredError()
    return parts[1]


class MoodleRest:
    """Minimal Moodle REST transport with redacted failures and no redirects."""

    def __init__(self, base_url: str, *, timeout: float = 15) -> None:
        self.origin = _origin(base_url)
        self.base_url = base_url.rstrip("/")
        self.endpoint = f"{self.base_url}/webservice/rest/server.php"
        self.timeout = timeout

    def call(self, token: str, function: str, **params: object) -> Any:
        if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token):
            raise PrincipalRequiredError()
        failure: type[Exception] | None = None
        try:
            response = requests.post(
                self.endpoint,
                data={**params, "wstoken": token, "wsfunction": function, "moodlewsrestformat": "json"},
                timeout=self.timeout,
                allow_redirects=False,
            )
            if response.status_code == 401:
                raise PrincipalRequiredError()
            if response.status_code != 200:
                raise MoodleAuthorizationUnavailableError()
            data = response.json()
            if isinstance(data, dict) and ("exception" in data or "errorcode" in data):
                if data.get("errorcode") in {"invalidtoken", "invalidlogin"}:
                    raise PrincipalRequiredError()
                raise MoodleAuthorizationUnavailableError()
            return data
        except PrincipalRequiredError:
            failure = PrincipalRequiredError
        except (requests.RequestException, ValueError, TypeError, MoodleAuthorizationUnavailableError):
            failure = MoodleAuthorizationUnavailableError
        # Leave the handler before raising to avoid retaining credential-bearing
        # request URLs in public exception context/tracebacks.
        raise failure()


class CapabilityEvidence(Protocol):
    def allows(self, user_id: int, course_id: int, capability: str) -> bool: ...


class MoodleCoreCapabilityEvidence:
    """Checks a verified user's course capability with a separate service token.

    The integration account only asks Moodle for evidence. Its enrollment is
    never used as the end user's authorization.
    """

    def __init__(self, rest: MoodleRest, service_token: str) -> None:
        if not service_token:
            raise ValueError("Moodle capability service token is required.")
        self.rest = rest
        self._service_token = service_token

    def allows(self, user_id: int, course_id: int, capability: str) -> bool:
        data = self.rest.call(
            self._service_token,
            "core_enrol_get_enrolled_users_with_capability",
            **{
                "coursecapabilities[0][courseid]": course_id,
                "coursecapabilities[0][capabilities][0]": capability,
                "options[0][name]": "onlyactive",
                "options[0][value]": 1,
                "options[1][name]": "userfields",
                "options[1][value]": "id",
            },
        )
        if not isinstance(data, list) or len(data) != 1:
            raise MoodleAuthorizationUnavailableError()
        row = data[0]
        if (not isinstance(row, dict) or row.get("courseid") != course_id or
                row.get("capability") != capability or not isinstance(row.get("users"), list)):
            raise MoodleAuthorizationUnavailableError()
        ids: set[int] = set()
        for user in row["users"]:
            if not isinstance(user, dict):
                raise MoodleAuthorizationUnavailableError()
            identity = _positive_id(user.get("id"))
            if identity in ids:
                raise MoodleAuthorizationUnavailableError()
            ids.add(identity)
        return user_id in ids


@dataclass(frozen=True)
class AuthorizedMoodleCourse:
    principal: VerifiedPrincipal
    binding: MoodleUserBinding
    scope: CanonicalCourseScope
    decision: AuthorizationDecision


@dataclass(frozen=True)
class MoodleResource:
    moodle_course_id: int
    resource_id: int
    document_id: str
    filename: str
    mime_type: str
    source_version_hint: str | None
    file_size: int | None
    file_url: str = field(repr=False, compare=False)


@dataclass(frozen=True)
class MoodleSourceVersion:
    moodle_namespace: str
    moodle_course_id: int
    document_id: str
    content_hash: str
    filename: str
    source_version_hint: str | None = None


@dataclass(frozen=True)
class MoodleLifecycleSignal:
    kind: str  # CANDIDATE, UNCHANGED, or TOMBSTONE
    moodle_course_id: int
    document_id: str
    content_hash: str | None
    previous_hash: str | None


def lifecycle_signals(
    previous: list[MoodleSourceVersion], current: list[MoodleSourceVersion], *,
    moodle_namespace: str, course_id: int,
) -> list[MoodleLifecycleSignal]:
    """Plan source-side changes; publication remains downstream's authority."""
    def keyed(values: list[MoodleSourceVersion]) -> dict[str, MoodleSourceVersion]:
        result: dict[str, MoodleSourceVersion] = {}
        for value in values:
            if (value.moodle_namespace != moodle_namespace or
                    value.moodle_course_id != course_id or value.document_id in result):
                raise MoodleAuthorizationUnavailableError()
            result[value.document_id] = value
        return result

    old, new = keyed(previous), keyed(current)
    signals = []
    for key in sorted(old.keys() | new.keys()):
        before, after = old.get(key), new.get(key)
        signals.append(MoodleLifecycleSignal(
            kind="TOMBSTONE" if after is None else "UNCHANGED" if before and before.content_hash == after.content_hash else "CANDIDATE",
            moodle_course_id=course_id,
            document_id=key,
            content_hash=after.content_hash if after else None,
            previous_hash=before.content_hash if before else None,
        ))
    return signals


def moodle_document_id(
    moodle_namespace: str, course_id: int, resource_id: int, file_id: int | None = None,
) -> str:
    """Stable, bounded source ID unique across Moodle deployments and courses."""
    site_key = hashlib.sha256(moodle_namespace.encode()).hexdigest()[:20]
    suffix = f":file:{file_id}" if file_id is not None else ""
    return f"moodle:{site_key}:course:{course_id}:resource:{resource_id}{suffix}"


def source_version(document: SourceDocument) -> MoodleSourceVersion:
    """Project a downloaded Moodle document into a transport-free snapshot."""
    if document.source != "moodle":
        raise MoodleAuthorizationUnavailableError()
    course_id = _positive_id(document.metadata.get("moodle_course_id"))
    namespace = document.metadata.get("moodle_namespace")
    if not isinstance(namespace, str) or not namespace:
        raise MoodleAuthorizationUnavailableError()
    return MoodleSourceVersion(
        moodle_namespace=namespace,
        moodle_course_id=course_id,
        document_id=document.document_id,
        content_hash=document.content_hash,
        filename=document.filename,
        source_version_hint=document.metadata.get("source_version_hint"),
    )


class MoodleTrustBoundary:
    """Production composition for a personal Moodle token and numeric course."""

    def __init__(
        self,
        base_url: str,
        *,
        kb_by_course_id: Mapping[int, str] | None = None,
        course_kb_resolver: Callable[[str], str] | None = None,
        capability_evidence: CapabilityEvidence | None = None,
        sync_capability: str = "moodle/course:manageactivities",
        file_credential_parameter: str = "token",
        max_file_bytes: int = 25 * 1024 * 1024,
    ) -> None:
        if file_credential_parameter not in {"token", "wstoken"}:
            raise ValueError("Moodle file credential transport is not configured safely.")
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.rest = MoodleRest(base_url)
        self.namespace = self.rest.base_url
        self.kb_by_course_id = dict(kb_by_course_id or {})
        self.course_kb_resolver = course_kb_resolver
        if (any(type(key) is not int or key <= 0 or not isinstance(value, str) or not value.strip()
                for key, value in self.kb_by_course_id.items()) or
                len(set(self.kb_by_course_id.values())) != len(self.kb_by_course_id)):
            raise ValueError("Canonical Moodle course to KB mapping is ambiguous.")
        self.capability_evidence = capability_evidence
        self.sync_capability = sync_capability
        self.file_credential_parameter = file_credential_parameter
        self.max_file_bytes = max_file_bytes

    def _identity(self, token: str) -> tuple[VerifiedPrincipal, MoodleUserBinding]:
        data = self.rest.call(token, "core_webservice_get_site_info")
        try:
            valid_site = (
                isinstance(data, dict) and
                _origin(data.get("siteurl")) == self.rest.origin and
                data["siteurl"].rstrip("/") == self.namespace
            )
        except ValueError:
            valid_site = False
        if not valid_site:
            raise MoodleAuthorizationUnavailableError()
        user_id = _positive_id(data.get("userid"))
        functions = data.get("functions")
        if (not isinstance(functions, list) or
                any(not isinstance(f, dict) or not isinstance(f.get("name"), str) for f in functions) or
                "core_enrol_get_users_courses" not in {f["name"] for f in functions}):
            raise MoodleAuthorizationUnavailableError()
        now = datetime.now(timezone.utc)
        principal = VerifiedPrincipal(
            subject=str(user_id), issuer=f"moodle:{self.namespace}",
            authenticated_at=now, expires_at=now + timedelta(seconds=30),
        )
        binding = MoodleUserBinding(
            issuer=principal.issuer, subject=principal.subject,
            moodle_namespace=self.namespace, moodle_user_id=user_id,
            binding_version=1, active=True,
        )
        return principal, binding

    def verify_credential(self, token: str) -> tuple[VerifiedPrincipal, MoodleUserBinding]:
        """Verify a personal token live; the returned values contain no token."""
        return self._identity(token)

    def _courses(self, token: str, user_id: int) -> dict[int, dict[str, Any]]:
        data = self.rest.call(token, "core_enrol_get_users_courses", userid=user_id, returnusercount=0)
        if not isinstance(data, list):
            raise MoodleAuthorizationUnavailableError()
        courses: dict[int, dict[str, Any]] = {}
        names: set[str] = set()
        for row in data:
            if not isinstance(row, dict):
                raise MoodleAuthorizationUnavailableError()
            identity = _positive_id(row.get("id"))
            shortname = row.get("shortname")
            if (not isinstance(shortname, str) or not shortname.strip() or
                    identity in courses or shortname.strip().casefold() in names):
                raise MoodleAuthorizationUnavailableError()
            courses[identity] = row
            names.add(shortname.strip().casefold())
        return courses

    def enrolled_courses(self, token):
        principal,binding=self._identity(token)
        return principal,binding,list(self._courses(token,binding.moodle_user_id).values())

    def authorize(self, token: str, selector: int | str, action: CourseAction) -> AuthorizedMoodleCourse:
        if not isinstance(action, CourseAction) or type(selector) not in {int, str}:
            raise CourseAccessDeniedError()
        principal, binding = self._identity(token)
        courses = self._courses(token, binding.moodle_user_id)
        matches = [row for row in courses.values() if
                   (type(selector) is int and row["id"] == selector) or
                   (type(selector) is str and row["shortname"].strip().casefold() == selector.strip().casefold())]
        if len(matches) != 1:
            raise CourseAccessDeniedError()
        course = matches[0]
        course_id = course["id"]
        mapping=dict(self.kb_by_course_id)
        if self.course_kb_resolver is not None:
            try:
                for row in courses.values():
                    mapping.setdefault(row["id"],self.course_kb_resolver(row["shortname"].strip()))
            except Exception:
                raise MoodleAuthorizationUnavailableError() from None
        if len(set(mapping.values()))!=len(mapping): raise MoodleAuthorizationUnavailableError()
        kb_id=mapping.get(course_id)
        if not isinstance(kb_id,str) or not kb_id.strip(): raise MoodleAuthorizationUnavailableError()
        scope=CanonicalCourseScope.create(self.namespace,course_id,course["shortname"].strip(),kb_id)

        def bound_authorizer(_: MoodleUserBinding, numeric_id: int, requested: CourseAction) -> AuthorizationDecision:
            allowed = numeric_id == course_id and requested is CourseAction.QUERY_COURSE
            if requested is CourseAction.SYNC_COURSE_RESOURCE and numeric_id == course_id:
                if self.capability_evidence is None:
                    raise MoodleAuthorizationUnavailableError()
                allowed = self.capability_evidence.allows(binding.moodle_user_id, course_id, self.sync_capability)
                if type(allowed) is not bool: raise MoodleAuthorizationUnavailableError()
            return AuthorizationDecision(
                allowed=allowed, reason_code="moodle_live_evidence" if allowed else "moodle_capability_denied",
                moodle_course_id=numeric_id, action=requested,
                decided_at=datetime.now(timezone.utc), policy_version="moodle-personal-v1", cache_state=CacheState.LIVE,
            )

        policy = CourseAuthorizationPolicy(
            moodle_namespace=self.namespace,
            principal_resolver=lambda _: principal,
            binding_resolver=lambda _: binding,
            course_authorizer=bound_authorizer,
        )
        decision = policy.authorize(None, course_id, action)
        return AuthorizedMoodleCourse(principal, binding, scope, decision)

    def discover(self, token: str, selector: int | str) -> tuple[AuthorizedMoodleCourse, list[MoodleResource]]:
        context = self.authorize(token, selector, CourseAction.SYNC_COURSE_RESOURCE)
        course_id = context.scope.moodle_course_id
        data = self.rest.call(token, "mod_resource_get_resources_by_courses", **{"courseids[0]": course_id})
        if not isinstance(data, dict) or not isinstance(data.get("resources"), list):
            raise MoodleAuthorizationUnavailableError()
        resources: list[MoodleResource] = []
        seen: set[str] = set()
        for row in data["resources"]:
            if not isinstance(row, dict):
                raise MoodleAuthorizationUnavailableError()
            if "course" in row and row["course"] != course_id:
                raise MoodleAuthorizationUnavailableError()
            resource_id = _positive_id(row.get("id"))
            files = row.get("contentfiles")
            if not isinstance(files, list):
                raise MoodleAuthorizationUnavailableError()
            for file in files:
                if not isinstance(file, dict):
                    raise MoodleAuthorizationUnavailableError()
                filename, url = file.get("filename"), file.get("fileurl")
                if not isinstance(filename, str) or not filename or not isinstance(url, str):
                    raise MoodleAuthorizationUnavailableError()
                if ("/" in filename or "\\" in filename or filename in {".", ".."} or
                        not isinstance(file.get("mimetype") or "application/octet-stream", str)):
                    raise MoodleAuthorizationUnavailableError()
                self._validate_file_url(url)
                # Moodle resource module ID survives a single-file rename.
                # Multiple files require a Moodle file ID; no ordinal or filename
                # is accepted as a substitute for stable identity.
                file_id = file.get("id") if len(files) > 1 else None
                if len(files) > 1:
                    file_id = _positive_id(file_id)
                document_id = moodle_document_id(self.namespace, course_id, resource_id, file_id)
                if document_id in seen:
                    raise MoodleAuthorizationUnavailableError()
                seen.add(document_id)
                hint = file.get("timemodified")
                size = file.get("filesize")
                if size is not None and (type(size) is not int or size < 0):
                    raise MoodleAuthorizationUnavailableError()
                resources.append(MoodleResource(
                    moodle_course_id=course_id, resource_id=resource_id,
                    document_id=document_id, filename=filename,
                    mime_type=file.get("mimetype") or "application/octet-stream",
                    source_version_hint=str(hint) if hint is not None else None,
                    file_size=size,
                    file_url=url,
                ))
        resources.sort(key=lambda item: (item.resource_id, item.document_id))
        return context, resources

    def _validate_file_url(self, url: str) -> None:
        try:
            parsed = urlsplit(url)
            moodle_path = urlsplit(self.namespace).path.rstrip("/")
            if (_origin(url) != self.rest.origin or not parsed.path.startswith(
                f"{moodle_path}/webservice/pluginfile.php/"
            )):
                raise ValueError
        except (TypeError, ValueError):
            raise MoodleAuthorizationUnavailableError() from None

    def download(self, token: str, selector: int | str, document_id: str) -> SourceDocument:
        context, resources = self.discover(token, selector)
        matched = [resource for resource in resources if resource.document_id == document_id]
        if len(matched) != 1:
            raise CourseAccessDeniedError()
        return self._download_resource(token, context, matched[0])

    def scan_course(
        self, token: str, selector: int | str,
    ) -> tuple[AuthorizedMoodleCourse, list[SourceDocument]]:
        """Return a complete, stable authorized source snapshot or fail closed.

        An empty result is authoritative only when both discovery calls succeed.
        Downstream may compare that snapshot with its last published versions to
        emit tombstones; a partial/failed scan must never imply deletion.
        """
        context, resources = self.discover(token, selector)
        documents = [self._download_resource(token, context, resource) for resource in resources]
        end_context, end_resources = self.discover(token, context.scope.moodle_course_id)
        if (end_context.scope != context.scope or end_context.binding != context.binding or
                end_resources != resources or
                [item.file_url for item in end_resources] != [item.file_url for item in resources]):
            raise MoodleAuthorizationUnavailableError()
        return end_context, documents

    def _download_resource(
        self, token: str, context: AuthorizedMoodleCourse, resource: MoodleResource,
    ) -> SourceDocument:
        if resource.moodle_course_id != context.scope.moodle_course_id:
            raise CourseAccessDeniedError()
        if resource.file_size is not None and resource.file_size > self.max_file_bytes:
            raise MoodleAuthorizationUnavailableError()
        failure: type[Exception] | None = None
        try:
            response = requests.get(
                resource.file_url, params={self.file_credential_parameter: token},
                timeout=30, allow_redirects=False, stream=True,
            )
            if response.status_code != 200:
                raise MoodleAuthorizationUnavailableError()
            data = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                data.extend(chunk)
                if len(data) > self.max_file_bytes:
                    raise MoodleAuthorizationUnavailableError()
            content = bytes(data)
            content_type = response.headers.get("Content-Type", "").lower()
            if (not content or content_type.startswith("text/html") or
                    content.lstrip().lower().startswith((b"<html", b"<!doctype html")) or
                    (resource.filename.lower().endswith(".pdf") and not content.startswith(b"%PDF-"))):
                raise MoodleAuthorizationUnavailableError()
            return SourceDocument(
                course_id=context.scope.canonical_course_key,
                document_id=resource.document_id,
                filename=resource.filename,
                mime_type=resource.mime_type,
                source="moodle",
                content=content,
                metadata={
                    "moodle_namespace": context.scope.moodle_namespace,
                    "moodle_course_id": context.scope.moodle_course_id,
                    "moodle_resource_id": resource.resource_id,
                    "source_version_hint": resource.source_version_hint,
                    "moodle_file_size": resource.file_size,
                    "scope_version": context.scope.scope_version,
                },
            )
        except (requests.RequestException, ValueError, TypeError, MoodleAuthorizationUnavailableError):
            failure = MoodleAuthorizationUnavailableError
        finally:
            if "response" in locals():
                response.close()
        raise failure()
