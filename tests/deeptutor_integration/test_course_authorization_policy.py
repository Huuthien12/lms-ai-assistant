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


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)
UNSET = object()


def principal(*, expired=False):
    return VerifiedPrincipal(
        "student-1",
        "https://issuer.example",
        NOW,
        datetime(2099, 1, 1, tzinfo=timezone.utc),
    ) if not expired else VerifiedPrincipal(
        "student-1", "https://issuer.example", NOW - timedelta(hours=2), NOW - timedelta(hours=1)
    )


def binding(*, active=True, issuer="https://issuer.example", subject="student-1", namespace="moodle-local"):
    return MoodleUserBinding(issuer, subject, namespace, 3, 1, active)


def decision(*, allowed=True, course_id=2, action=CourseAction.QUERY_COURSE, cache_state=CacheState.LIVE):
    return AuthorizationDecision(allowed, "allowed" if allowed else "course_access_denied", course_id, action, NOW, "v1", cache_state)


def policy(*, principal_resolver=UNSET, binding_resolver=UNSET, authorizer=UNSET, cache_policy=None):
    return CourseAuthorizationPolicy(
        "moodle-local",
        principal_resolver=(lambda _: principal()) if principal_resolver is UNSET else principal_resolver,
        binding_resolver=(lambda _: binding()) if binding_resolver is UNSET else binding_resolver,
        course_authorizer=(lambda _, course_id, action: decision(course_id=course_id, action=action)) if authorizer is UNSET else authorizer,
        query_cache_policy=cache_policy,
    )


def test_live_allow_returns_exact_decision_and_uses_binding():
    authorizer = Mock(return_value=decision())
    result = policy(authorizer=authorizer).authorize({}, 2, CourseAction.QUERY_COURSE, now=NOW)
    assert result.allowed is True
    assert authorizer.call_args.args[0] == binding()
    assert authorizer.call_args.args[1:] == (2, CourseAction.QUERY_COURSE)


def test_missing_or_forged_principal_is_401_without_side_effects():
    authorizer = Mock()
    guarded = policy(principal_resolver=lambda _: None, authorizer=authorizer)
    with pytest.raises(PrincipalRequiredError) as error:
        guarded.authorize({"headers": {"X-User-Id": "admin", "X-Internal-Api-Key": "fake-service-token"}}, 2, CourseAction.QUERY_COURSE)
    assert error.value.status_code == 401
    authorizer.assert_not_called()


def test_expired_principal_is_401():
    with pytest.raises(PrincipalRequiredError):
        policy(principal_resolver=lambda _: principal(expired=True)).authorize({}, 2, CourseAction.QUERY_COURSE, now=NOW)


@pytest.mark.parametrize(
    "binding_resolver",
    [lambda _: None, lambda _: binding(active=False), lambda _: [binding(), binding()]],
    ids=["missing", "inactive", "ambiguous"],
)
def test_missing_inactive_or_ambiguous_binding_is_403(binding_resolver):
    with pytest.raises(MoodleBindingDeniedError) as error:
        policy(binding_resolver=binding_resolver).authorize({}, 2, CourseAction.QUERY_COURSE)
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    "binding_value",
    [binding(issuer="https://other.example"), binding(subject="other-user"), binding(namespace="other-moodle")],
    ids=["issuer", "subject", "namespace"],
)
def test_binding_mismatch_is_403(binding_value):
    with pytest.raises(MoodleBindingDeniedError):
        policy(binding_resolver=lambda _: binding_value).authorize({}, 2, CourseAction.QUERY_COURSE)


@pytest.mark.parametrize(
    "bad_decision",
    [decision(course_id=9), decision(action=CourseAction.SYNC_COURSE_RESOURCE), decision(allowed=False)],
    ids=["wrong-course", "wrong-action", "explicit-denial"],
)
def test_non_exact_or_denied_decision_is_403(bad_decision):
    with pytest.raises(CourseAccessDeniedError):
        policy(authorizer=lambda *_: bad_decision).authorize({}, 2, CourseAction.QUERY_COURSE)


@pytest.mark.parametrize("missing", ["principal_resolver", "binding_resolver", "course_authorizer"])
def test_missing_dependency_is_503(missing):
    values = {"principal_resolver": lambda _: principal(), "binding_resolver": lambda _: binding(), "authorizer": lambda *_: decision()}
    if missing == "principal_resolver":
        values["principal_resolver"] = None
    elif missing == "binding_resolver":
        values["binding_resolver"] = None
    else:
        values["authorizer"] = None
    with pytest.raises(AuthorizationNotConfiguredError) as error:
        policy(principal_resolver=values["principal_resolver"], binding_resolver=values["binding_resolver"], authorizer=values["authorizer"]).authorize({}, 2, CourseAction.QUERY_COURSE)
    assert error.value.status_code == 503


def test_moodle_unavailable_is_503_and_sanitized():
    def unavailable(*_):
        raise MoodleAuthorizationUnavailableError()

    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        policy(authorizer=unavailable).authorize({}, 2, CourseAction.QUERY_COURSE)
    assert error.value.public_payload() == {"code": "moodle_authorization_unavailable", "message": "Moodle authorization is unavailable."}


def test_sync_and_query_reject_fresh_cache_by_default():
    for action in (CourseAction.QUERY_COURSE, CourseAction.SYNC_COURSE_RESOURCE):
        with pytest.raises(CourseAccessDeniedError):
            policy(authorizer=lambda _, course_id, requested_action: decision(course_id=course_id, action=requested_action, cache_state=CacheState.FRESH_CACHE)).authorize({}, 2, action)


def test_explicit_server_cache_policy_can_only_enable_fresh_query():
    result = policy(
        authorizer=lambda _, course_id, action: decision(course_id=course_id, action=action, cache_state=CacheState.FRESH_CACHE),
        cache_policy=lambda _: True,
    ).authorize({}, 2, CourseAction.QUERY_COURSE)
    assert result.cache_state is CacheState.FRESH_CACHE


@pytest.mark.parametrize(
    "cache_policy",
    [
        lambda _: (_ for _ in ()).throw(RuntimeError("https://moodle.example/?wstoken=synthetic-cache-token")),
        lambda _: _raise_chained(MoodleAuthorizationUnavailableError),
    ],
    ids=["generic", "typed-chained"],
)
def test_cache_policy_failure_is_sanitized_without_context(cache_policy):
    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        policy(
            authorizer=lambda _, course_id, action: decision(course_id=course_id, action=action, cache_state=CacheState.FRESH_CACHE),
            cache_policy=cache_policy,
        ).authorize({}, 2, CourseAction.QUERY_COURSE)
    rendered = "".join(traceback.format_exception(error.value))
    assert "synthetic-cache-token" not in rendered
    assert error.value.status_code == 503
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_unexpected_authorizer_error_is_safe_503():
    def broken(*_):
        raise RuntimeError("https://moodle.example/?wstoken=fake-token")

    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        policy(authorizer=broken).authorize({}, 2, CourseAction.QUERY_COURSE)
    assert "fake-token" not in str(error.value)
    assert error.value.status_code == 503


def _raise_chained(error_type):
    try:
        raise RuntimeError("https://moodle.example/?wstoken=synthetic-secret")
    except RuntimeError as original:
        raise error_type() from original


@pytest.mark.parametrize(
    ("configured_policy", "error_type"),
    [
        (lambda: policy(principal_resolver=lambda _: _raise_chained(PrincipalRequiredError)), PrincipalRequiredError),
        (lambda: policy(binding_resolver=lambda _: _raise_chained(MoodleBindingDeniedError)), MoodleBindingDeniedError),
        (lambda: policy(authorizer=lambda *_: _raise_chained(CourseAccessDeniedError)), CourseAccessDeniedError),
    ],
    ids=["principal", "binding", "authorizer"],
)
def test_chained_dependency_errors_are_replaced_without_sensitive_traceback(configured_policy, error_type):
    with pytest.raises(error_type) as error:
        configured_policy().authorize({}, 2, CourseAction.QUERY_COURSE)
    rendered = "".join(traceback.format_exception(error.value))
    assert "synthetic-secret" not in rendered
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


@pytest.mark.parametrize(
    "configured_policy",
    [
        lambda: policy(principal_resolver=lambda _: (_ for _ in ()).throw(RuntimeError("idp offline"))),
        lambda: policy(binding_resolver=lambda _: (_ for _ in ()).throw(RuntimeError("binding store offline"))),
        lambda: policy(authorizer=lambda *_: (_ for _ in ()).throw(RuntimeError("moodle offline"))),
    ],
    ids=["principal", "binding", "authorizer"],
)
def test_unexpected_dependency_errors_map_to_sanitized_503(configured_policy):
    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        configured_policy().authorize({}, 2, CourseAction.QUERY_COURSE)
    assert error.value.public_payload() == {"code": "moodle_authorization_unavailable", "message": "Moodle authorization is unavailable."}


@pytest.mark.parametrize(
    "configured_policy",
    [
        lambda: policy(principal_resolver=lambda _: _raise_chained(MoodleAuthorizationUnavailableError)),
        lambda: policy(binding_resolver=lambda _: _raise_chained(MoodleAuthorizationUnavailableError)),
        lambda: policy(authorizer=lambda *_: _raise_chained(MoodleAuthorizationUnavailableError)),
    ],
    ids=["principal", "binding", "authorizer"],
)
def test_explicit_dependency_unavailability_is_sanitized_503(configured_policy):
    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        configured_policy().authorize({}, 2, CourseAction.QUERY_COURSE)
    assert "synthetic-secret" not in "".join(traceback.format_exception(error.value))
    assert error.value.__cause__ is None
    assert error.value.__context__ is None


def test_policy_has_no_retrieval_llm_or_download_dependencies():
    assert not hasattr(CourseAuthorizationPolicy, "retrieve")
    assert not hasattr(CourseAuthorizationPolicy, "llm")
    assert not hasattr(CourseAuthorizationPolicy, "download")
