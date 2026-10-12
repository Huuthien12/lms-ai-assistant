from datetime import datetime, timedelta, timezone
import traceback
from unittest.mock import Mock

import pytest

from deeptutor_integration.auth_contracts import (
    AuthorizationDecision,
    AuthorizationNotConfiguredError,
    CacheState,
    CourseAccessDeniedError,
    CourseAction,
    MoodleAuthorizationUnavailableError,
    MoodleBindingDeniedError,
    MoodleUserBinding,
    PrincipalRequiredError,
    VerifiedPrincipal,
)
from deeptutor_integration.course_authorization_policy import CourseAuthorizationPolicy
from deeptutor_integration.shared_query_authorization import (
    CanonicalCourseScope,
    SharedQueryAuthorizationAdapter,
)


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
UNSET = object()


def principal(*, expired=False):
    if expired:
        return VerifiedPrincipal("student", "issuer", NOW - timedelta(hours=2), NOW - timedelta(hours=1))
    return VerifiedPrincipal("student", "issuer", NOW, datetime(2099, 1, 1, tzinfo=timezone.utc))


def binding(*, active=True, version=1, namespace="moodle"):
    return MoodleUserBinding("issuer", "student", namespace, 3, version, active)


def scope(*, version="scope-v1", kb_id="kb-int1339", namespace="moodle"):
    return CanonicalCourseScope(namespace, 2, "INT1339", kb_id, version)


def decision(*, allowed=True):
    return AuthorizationDecision(allowed, "allowed" if allowed else "course_access_denied", 2, CourseAction.QUERY_COURSE, NOW, "v1", CacheState.LIVE)


def adapter(*, principal_resolver=UNSET, binding_resolver=UNSET, scope_resolver=UNSET, authorizer=UNSET):
    principal_resolver = (lambda _: principal()) if principal_resolver is UNSET else principal_resolver
    binding_resolver = (lambda _: binding()) if binding_resolver is UNSET else binding_resolver
    scope_resolver = (lambda _: scope()) if scope_resolver is UNSET else scope_resolver
    authorizer = (lambda *_: decision()) if authorizer is UNSET else authorizer
    policy = CourseAuthorizationPolicy("moodle", principal_resolver, binding_resolver, authorizer)
    return SharedQueryAuthorizationAdapter(principal_resolver, binding_resolver, scope_resolver, policy)


def test_valid_context_is_immutable_and_uses_server_owned_scope():
    context = adapter().authorize({}, "INT1339", requested_kb_id="kb-int1339", now=NOW)
    assert context.scope.moodle_course_id == 2
    assert context.decision.allowed is True
    with pytest.raises(AttributeError):
        context.scope.kb_id = "other"


@pytest.mark.parametrize("resolver", [lambda _: None, lambda _: principal(expired=True)], ids=["missing", "expired"])
def test_missing_or_invalid_principal_is_401(resolver):
    course_authorizer = Mock()
    with pytest.raises(PrincipalRequiredError) as error:
        adapter(principal_resolver=resolver, authorizer=course_authorizer).authorize({}, "INT1339", now=NOW)
    assert error.value.status_code == 401
    course_authorizer.assert_not_called()


@pytest.mark.parametrize(
    "resolver",
    [lambda _: None, lambda _: binding(active=False), lambda _: [binding(), binding()]],
    ids=["missing", "revoked", "ambiguous"],
)
def test_invalid_binding_is_403(resolver):
    with pytest.raises(MoodleBindingDeniedError) as error:
        adapter(binding_resolver=resolver).authorize({}, "INT1339", now=NOW)
    assert error.value.status_code == 403


def test_scope_namespace_and_client_kb_mismatch_are_denied():
    with pytest.raises(CourseAccessDeniedError):
        adapter(scope_resolver=lambda _: scope(namespace="other")).authorize({}, "INT1339", now=NOW)
    with pytest.raises(CourseAccessDeniedError):
        adapter().authorize({}, "INT1339", requested_kb_id="client-chosen-kb", now=NOW)


def test_missing_or_unavailable_dependency_is_503():
    missing = SharedQueryAuthorizationAdapter(None, None, None, None)
    with pytest.raises(AuthorizationNotConfiguredError) as error:
        missing.authorize({}, "INT1339", now=NOW)
    assert error.value.status_code == 503
    with pytest.raises(MoodleAuthorizationUnavailableError):
        adapter(scope_resolver=lambda _: (_ for _ in ()).throw(RuntimeError("scope offline"))).authorize({}, "INT1339", now=NOW)


def test_policy_denial_is_403():
    with pytest.raises(CourseAccessDeniedError):
        adapter(authorizer=lambda *_: decision(allowed=False)).authorize({}, "INT1339", now=NOW)


def test_reauthorization_rejects_binding_or_scope_version_change():
    state = {"binding": binding(version=1), "scope": scope(version="scope-v1")}
    shared = adapter(binding_resolver=lambda _: state["binding"], scope_resolver=lambda _: state["scope"])
    previous = shared.authorize({}, "INT1339", now=NOW)
    state["binding"] = binding(version=2)
    with pytest.raises(CourseAccessDeniedError):
        shared.reauthorize({}, previous, now=NOW)
    state["binding"] = binding(version=1)
    state["scope"] = scope(version="scope-v2")
    with pytest.raises(CourseAccessDeniedError):
        shared.reauthorize({}, previous, now=NOW)


def test_reauthorization_denies_revocation_before_llm_and_never_calls_downstream():
    state = {"binding": binding(active=True)}
    course_authorizer, downstream = Mock(side_effect=lambda *_: decision()), Mock()
    shared = adapter(binding_resolver=lambda _: state["binding"], authorizer=course_authorizer)
    previous = shared.authorize({}, "INT1339", now=NOW)
    state["binding"] = binding(active=False)
    with pytest.raises(MoodleBindingDeniedError):
        shared.reauthorize({}, previous, now=NOW)
    downstream.assert_not_called()


def test_misaligned_policy_dependencies_fail_closed():
    principal_resolver = lambda _: principal()
    binding_resolver = lambda _: binding()
    policy = CourseAuthorizationPolicy("moodle", lambda _: principal(), binding_resolver, lambda *_: decision())
    shared = SharedQueryAuthorizationAdapter(principal_resolver, binding_resolver, lambda _: scope(), policy)
    with pytest.raises(AuthorizationNotConfiguredError):
        shared.authorize({}, "INT1339", now=NOW)


def test_synthetic_dependency_secret_is_not_exposed():
    def broken(_):
        try:
            raise RuntimeError("https://issuer.example/?token=synthetic-adapter-secret")
        except RuntimeError as original:
            raise MoodleAuthorizationUnavailableError() from original

    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        adapter(principal_resolver=broken).authorize({}, "INT1339", now=NOW)
    rendered = "".join(traceback.format_exception(error.value))
    assert "synthetic-adapter-secret" not in rendered
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_adapter_has_no_retrieval_or_llm_operations():
    assert not hasattr(SharedQueryAuthorizationAdapter, "retrieve")
    assert not hasattr(SharedQueryAuthorizationAdapter, "chat")
