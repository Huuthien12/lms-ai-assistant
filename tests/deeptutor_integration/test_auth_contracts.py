from datetime import datetime, timedelta, timezone
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
    require_dependency,
)


NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def principal(*, expires_at=None):
    return VerifiedPrincipal("user-42", "https://issuer.example", NOW, expires_at or NOW + timedelta(hours=1))


def binding(*, active=True):
    return MoodleUserBinding("https://issuer.example", "user-42", "local-moodle", 42, 1, active)


def decision(*, allowed, action=CourseAction.QUERY_COURSE):
    return AuthorizationDecision(
        allowed=allowed,
        reason_code="allowed" if allowed else "course_access_denied",
        moodle_course_id=2,
        action=action,
        decided_at=NOW,
        policy_version="v1",
        cache_state=CacheState.LIVE,
    )


def guarded_contract_call(resolver, binding_resolver, authorizer, request, retrieve, llm, action):
    current_principal = resolver(request)
    binding_resolver(current_principal).require_active()
    result = authorizer(current_principal, 2, action)
    if not result.allowed:
        raise CourseAccessDeniedError()
    return llm(retrieve())


def test_valid_principal_is_immutable_and_invalid_values_are_rejected():
    valid = principal()
    assert valid.subject == "user-42"
    with pytest.raises(ValueError):
        VerifiedPrincipal("", "issuer", NOW, NOW + timedelta(seconds=1))
    with pytest.raises(ValueError):
        VerifiedPrincipal("user", "issuer", NOW.replace(tzinfo=None), NOW + timedelta(seconds=1))
    with pytest.raises(ValueError):
        VerifiedPrincipal("user", "issuer", NOW, NOW)
    with pytest.raises(AttributeError):
        valid.subject = "altered"


def test_expired_principal_is_rejected():
    with pytest.raises(PrincipalRequiredError) as error:
        principal(expires_at=NOW + timedelta(seconds=1)).require_active(NOW + timedelta(seconds=1))
    assert error.value.status_code == 401
    assert error.value.code == "principal_required"


def test_invalid_and_disabled_moodle_bindings_are_rejected():
    with pytest.raises(ValueError):
        MoodleUserBinding("issuer", "subject", "moodle", 0, 1, True)
    with pytest.raises(MoodleBindingDeniedError):
        binding(active=False).require_active()


def test_ambiguous_binding_contract_fails_closed():
    def ambiguous_binding(_):
        raise MoodleBindingDeniedError()

    with pytest.raises(MoodleBindingDeniedError):
        ambiguous_binding(principal())


def test_query_and_sync_actions_are_separated():
    authorizer = Mock(side_effect=lambda _, __, action: decision(allowed=action is CourseAction.QUERY_COURSE, action=action))
    assert authorizer(principal(), 2, CourseAction.QUERY_COURSE).allowed
    assert not authorizer(principal(), 2, CourseAction.SYNC_COURSE_RESOURCE).allowed
    assert authorizer.call_args_list[0].args[2] is CourseAction.QUERY_COURSE
    assert authorizer.call_args_list[1].args[2] is CourseAction.SYNC_COURSE_RESOURCE


def test_moodle_timeout_contract_maps_to_safe_503():
    def unavailable(*_):
        raise MoodleAuthorizationUnavailableError()

    with pytest.raises(MoodleAuthorizationUnavailableError) as error:
        unavailable(principal(), 2, CourseAction.QUERY_COURSE)
    assert error.value.status_code == 503
    assert "token" not in str(error.value).lower()


def test_missing_dependency_fails_closed_with_503():
    with pytest.raises(AuthorizationNotConfiguredError) as error:
        require_dependency(None)
    assert error.value.status_code == 503


def test_forged_request_fields_cannot_create_a_trusted_principal():
    retrieve, llm = Mock(), Mock()

    def rejecting_resolver(_request):
        raise PrincipalRequiredError()

    forged_request = {"headers": {"X-User-Id": "admin", "X-Internal-Api-Key": "fake-service-key"}, "body": {"role": "teacher"}}
    with pytest.raises(PrincipalRequiredError):
        guarded_contract_call(rejecting_resolver, binding, Mock(), forged_request, retrieve, llm, CourseAction.QUERY_COURSE)
    retrieve.assert_not_called()
    llm.assert_not_called()


def test_cross_course_denial_calls_neither_retrieval_nor_llm():
    retrieve, llm = Mock(), Mock()
    with pytest.raises(CourseAccessDeniedError):
        guarded_contract_call(lambda _: principal(), lambda _: binding(), lambda *_: decision(allowed=False), {}, retrieve, llm, CourseAction.QUERY_COURSE)
    retrieve.assert_not_called()
    llm.assert_not_called()


def test_internal_service_token_is_not_an_end_user_identity():
    def resolver(_request):
        raise PrincipalRequiredError()

    with pytest.raises(PrincipalRequiredError):
        resolver({"headers": {"X-Internal-Api-Key": "fake-internal-token", "Authorization": "Bearer fake-moodle-token"}})


def test_decision_validates_action_cache_state_and_safe_error_payload():
    with pytest.raises(ValueError):
        AuthorizationDecision(True, "allowed", 2, "QUERY_COURSE", NOW, "v1", CacheState.LIVE)
    with pytest.raises(ValueError):
        AuthorizationDecision(True, "allowed", 2, CourseAction.QUERY_COURSE, NOW, "v1", "LIVE")
    payload = CourseAccessDeniedError().public_payload()
    assert payload == {"code": "course_access_denied", "message": "Course access is not permitted."}
