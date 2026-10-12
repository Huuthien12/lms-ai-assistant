from __future__ import annotations

import hashlib
from unittest.mock import Mock, patch

import pytest
import requests

from deeptutor_integration.auth_contracts import (
    CourseAccessDeniedError, CourseAction, MoodleAuthorizationUnavailableError,
    PrincipalRequiredError,
)
from deeptutor_integration.moodle_trust import (
    MoodleCoreCapabilityEvidence, MoodleRest, MoodleSourceVersion,
    MoodleTrustBoundary, lifecycle_signals, moodle_document_id,
    personal_bearer_token, source_version,
)


@pytest.fixture(autouse=True)
def fake_file_transport(monkeypatch):
    # One fake records POST REST and GET file calls in their original sequence.
    monkeypatch.setattr("deeptutor_integration.moodle_trust.requests.get",lambda *a,**k:requests.post(*a,**k))


BASE = "https://moodle.example"
PERSON_A = "personal-A-secret"
PERSON_B = "personal-B-secret"
SERVICE = "capability-service-secret"


def result(data=None, *, content=b"", status=200, content_type="application/pdf"):
    response = Mock(status_code=status, headers={"Content-Type": content_type})
    response.json.return_value = data
    response.iter_content.return_value = [content]
    return response


def site(user_id):
    return {"siteurl": BASE, "userid": user_id,
            "functions": [{"name": "core_enrol_get_users_courses"}]}


def course(identity, name):
    return {"id": identity, "shortname": name, "fullname": name}


class Evidence:
    def __init__(self, allowed_users=(11,)):
        self.allowed_users = allowed_users
        self.calls = []

    def allows(self, user_id, course_id, capability):
        self.calls.append((user_id, course_id, capability))
        return user_id in self.allowed_users


def boundary(evidence=None):
    return MoodleTrustBoundary(BASE, kb_by_course_id={101: "kb-a", 202: "kb-b"},
                               capability_evidence=evidence)


def resources(*files):
    return {"resources": [{"id": 7, "contentfiles": list(files)}]}


def file(name="chapter.pdf", *, content_time=100):
    return {"filename": name, "mimetype": "application/pdf", "timemodified": content_time,
            "fileurl": f"{BASE}/webservice/pluginfile.php/3/mod_resource/content/7/{name}"}


DOC_ID = moodle_document_id(BASE, 101, 7)


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_two_users_two_courses_and_cross_course_denial(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]),
                            result(site(22)), result([course(202, "B")]),
                            result(site(11)), result([course(101, "A")])]
    trust = boundary()
    allowed_a = trust.authorize(PERSON_A, "A", CourseAction.QUERY_COURSE)
    allowed_b = trust.authorize(PERSON_B, 202, CourseAction.QUERY_COURSE)
    assert (allowed_a.scope.moodle_course_id, allowed_a.scope.kb_id) == (101, "kb-a")
    assert (allowed_b.scope.moodle_course_id, allowed_b.scope.kb_id) == (202, "kb-b")
    assert allowed_a.binding.moodle_user_id == 11
    with pytest.raises(CourseAccessDeniedError):
        trust.authorize(PERSON_A, 202, CourseAction.QUERY_COURSE)
    assert len(mock_get.call_args_list) == 6
    assert all("wstoken" in call.kwargs["data"] for call in mock_get.call_args_list)


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_invalid_missing_malformed_and_timeout_fail_before_discovery(mock_get):
    trust = boundary(Evidence())
    with pytest.raises(PrincipalRequiredError):
        trust.discover("", 101)
    assert mock_get.call_count == 0
    mock_get.side_effect = [result({"exception": "moodle_exception", "errorcode": "invalidtoken"}),
                            result({"userid": 11, "siteurl": BASE, "functions": []}),
                            requests.Timeout(f"{BASE}/?wstoken={PERSON_A}")]
    with pytest.raises(PrincipalRequiredError):
        trust.discover(PERSON_A, 101)
    with pytest.raises(MoodleAuthorizationUnavailableError):
        trust.discover(PERSON_A, 101)
    with pytest.raises(MoodleAuthorizationUnavailableError) as raised:
        trust.discover(PERSON_A, 101)
    assert PERSON_A not in str(raised.value)
    assert raised.value.__context__ is None
    assert mock_get.call_count == 3


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_ambiguous_course_or_missing_server_mapping_fails_closed(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A"), course(202, "A")]),
                            result(site(11)), result([course(101, "A")])]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary().authorize(PERSON_A, "A", CourseAction.QUERY_COURSE)
    no_mapping = MoodleTrustBoundary(BASE, kb_by_course_id={})
    with pytest.raises(MoodleAuthorizationUnavailableError):
        no_mapping.authorize(PERSON_A, 101, CourseAction.QUERY_COURSE)


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_lecturer_evidence_precedes_resource_discovery(mock_get):
    evidence = Evidence(allowed_users=(11,))
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]),
                            result(site(22)), result([course(202, "B")])]
    context = boundary(evidence).authorize(PERSON_A, 101, CourseAction.SYNC_COURSE_RESOURCE)
    assert context.decision.allowed
    with pytest.raises(CourseAccessDeniedError):
        boundary(evidence).discover(PERSON_B, 202)
    assert evidence.calls == [(11, 101, "moodle/course:manageactivities"),
                              (22, 202, "moodle/course:manageactivities")]
    assert mock_get.call_count == 4


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_authorized_pdf_update_and_rename_keep_source_identity(mock_get):
    evidence = Evidence()
    mock_get.side_effect = [
        result(site(11)), result([course(101, "A")]), result(resources(file())),
        result(content=b"%PDF-first"),
        result(site(11)), result([course(101, "A")]), result(resources(file("renamed.pdf", content_time=200))),
        result(content=b"%PDF-second"),
    ]
    trust = boundary(evidence)
    first = trust.download(PERSON_A, 101, DOC_ID)
    second = trust.download(PERSON_A, "A", DOC_ID)
    assert first.document_id == second.document_id == DOC_ID
    assert first.content_hash == hashlib.sha256(b"%PDF-first").hexdigest()
    assert first.content_hash != second.content_hash
    assert first.metadata["moodle_course_id"] == 101
    assert second.metadata["source_version_hint"] == "200"
    assert PERSON_A not in str(first.model_dump())
    signals = lifecycle_signals([source_version(first)], [source_version(second)],
                                moodle_namespace=BASE, course_id=101)
    assert [(signal.kind, signal.previous_hash, signal.content_hash) for signal in signals] == [
        ("CANDIDATE", first.content_hash, second.content_hash)]
    assert mock_get.call_args_list[3].kwargs["allow_redirects"] is False
    assert mock_get.call_args_list[3].kwargs["params"] == {"token": PERSON_A}


def test_lifecycle_idempotent_rename_delete_and_failed_publication():
    old = MoodleSourceVersion(BASE, 101, DOC_ID, "a" * 64, "old.pdf")
    rename = MoodleSourceVersion(BASE, 101, DOC_ID, "a" * 64, "renamed.pdf")
    assert lifecycle_signals([old], [rename], moodle_namespace=BASE, course_id=101)[0].kind == "UNCHANGED"
    deleted = lifecycle_signals([old], [], moodle_namespace=BASE, course_id=101)[0]
    assert (deleted.kind, deleted.content_hash, deleted.previous_hash) == ("TOMBSTONE", None, "a" * 64)
    # Candidate output contains no ACTIVE state; only a downstream publication
    # acknowledgement may supersede the previous retrieval artifact.
    changed = MoodleSourceVersion(BASE, 101, DOC_ID, "b" * 64, "new.pdf")
    assert lifecycle_signals([old], [changed], moodle_namespace=BASE, course_id=101)[0].kind == "CANDIDATE"


def test_bearer_parsing_and_ambiguous_kb_mapping():
    assert personal_bearer_token("Bearer personal-token") == "personal-token"
    for header in (None, "", "Basic x", "Bearer", "Bearer a b", "Bearer  a"):
        with pytest.raises(PrincipalRequiredError):
            personal_bearer_token(header)
    with pytest.raises(ValueError, match="ambiguous"):
        MoodleTrustBoundary(BASE, kb_by_course_id={101: "shared-kb", 202: "shared-kb"})


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_wrong_site_same_origin_and_forbidden_function_fail_closed(mock_get):
    mock_get.side_effect = [result({**site(11), "siteurl": BASE + "/other"}),
                            result({"exception": "required_capability_exception", "errorcode": "accessexception"})]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary().verify_credential(PERSON_A)
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary().verify_credential(PERSON_A)


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_core_capability_evidence_targets_verified_user_and_active_enrolment(mock_get):
    mock_get.return_value = result([{"courseid": 101, "capability": "moodle/course:manageactivities",
                                     "users": [{"id": 11}]}])
    evidence = MoodleCoreCapabilityEvidence(MoodleRest(BASE), SERVICE)
    assert evidence.allows(11, 101, "moodle/course:manageactivities")
    assert not evidence.allows(22, 101, "moodle/course:manageactivities")
    params = mock_get.call_args.kwargs["data"]
    assert params["wstoken"] == SERVICE
    assert params["options[0][name]"] == "onlyactive"
    assert params["options[0][value]"] == 1
    assert params["coursecapabilities[0][courseid]"] == 101


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_unsafe_discovery_url_never_downloads(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]),
                            result(resources({**file(), "fileurl": "https://evil.example/x"}))]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary(Evidence()).download(PERSON_A, 101, DOC_ID)
    assert mock_get.call_count == 3


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_complete_empty_scan_produces_delete_signal(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]), result({"resources": []}),
                            result(site(11)), result([course(101, "A")]), result({"resources": []})]
    context, docs = boundary(Evidence()).scan_course(PERSON_A, 101)
    assert docs == []
    prior = MoodleSourceVersion(BASE, 101, DOC_ID, "a" * 64, "chapter.pdf")
    assert lifecycle_signals([prior], [source_version(doc) for doc in docs],
                             moodle_namespace=BASE,
                             course_id=context.scope.moodle_course_id)[0].kind == "TOMBSTONE"


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_scan_fails_when_discovery_changes_during_download(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]), result(resources(file())),
                            result(content=b"%PDF-first"),
                            result(site(11)), result([course(101, "A")]), result({"resources": []})]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary(Evidence()).scan_course(PERSON_A, 101)


@pytest.mark.parametrize("bad_url", [
    "https://evil.example/webservice/pluginfile.php/1/file.pdf",
    f"{BASE}/webservice/pluginfile.php/1/file.pdf?token=embedded",
    f"{BASE}/webservice/pluginfile.php/1/file.pdf#fragment",
    f"https://user:secret@moodle.example/webservice/pluginfile.php/1/file.pdf",
    f"{BASE}/private/file.pdf",
])
@patch("deeptutor_integration.moodle_trust.requests.post")
def test_untrusted_file_locator_is_rejected_before_download(mock_get, bad_url):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]),
                            result(resources({**file(), "fileurl": bad_url}))]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary(Evidence()).download(PERSON_A, 101, DOC_ID)
    assert mock_get.call_count == 3


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_redirect_and_oversized_download_fail_closed(mock_get):
    trust = MoodleTrustBoundary(BASE, kb_by_course_id={101: "kb-a"},
                                capability_evidence=Evidence(), max_file_bytes=8)
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]), result(resources(file())),
                            result(status=302),
                            result(site(11)), result([course(101, "A")]), result(resources(file())),
                            result(content=b"%PDF-too-long")]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        trust.download(PERSON_A, 101, DOC_ID)
    with pytest.raises(MoodleAuthorizationUnavailableError):
        trust.download(PERSON_A, 101, DOC_ID)
    assert mock_get.call_args_list[3].kwargs["allow_redirects"] is False


@patch("deeptutor_integration.moodle_trust.requests.post")
def test_multi_file_without_stable_file_ids_is_unavailable(mock_get):
    mock_get.side_effect = [result(site(11)), result([course(101, "A")]),
                            result(resources(file("first.pdf"), file("second.pdf")))]
    with pytest.raises(MoodleAuthorizationUnavailableError):
        boundary(Evidence()).discover(PERSON_A, 101)
