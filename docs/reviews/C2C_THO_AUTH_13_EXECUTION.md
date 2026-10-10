# C2C THO-AUTH-13 — Authentication Contracts & Mock Security Tests

## Status

**EXECUTED (contract groundwork only).** This change intentionally does not
authenticate an end user, contact Moodle, or alter any production route.

## Workspace guard

- Project identity: **DeepTutor LMS AI Assistant** (repository README)
- Checkout directory: `C:\Users\PHUC THO\Documents\ChatGPT\lms-ai-assistant`
- Branch observed: `tho/moodle-download-security`
- HEAD observed: `0139f8e177a35f8192b8ecb715332f8a3e45a225`
- Existing untracked reports under `docs/reviews/` were preserved.

The implementation runtime could resolve the branch and HEAD, but Git
worktree-inspection commands (`git status` and `git diff`) returned `fatal:
this operation must be run in a work tree` after the focused test completed.
This is an environment/tooling limitation for final Git inspection, not a
source change. No Git-mutating command was issued.

## Files changed by this task

1. `deeptutor_integration/auth_contracts.py` — new backend-neutral contract
   module.
2. `tests/deeptutor_integration/test_auth_contracts.py` — new mocked contract
   tests.
3. `docs/reviews/C2C_THO_AUTH_13_EXECUTION.md` — this handoff report.

Production route files were not edited: `deeptutor_integration/api.py`,
`lms-dlu-demo/main.py`, and `lms-dlu-demo/grounded_chat_router.py` remain
outside the change boundary.

## Implemented contract types and dependencies

`auth_contracts.py` defines immutable, validated dataclasses:

- `VerifiedPrincipal(subject, issuer, authenticated_at, expires_at)` validates
  non-empty identity values, timezone-aware timestamps, and expiry ordering.
- `MoodleUserBinding(issuer, subject, moodle_namespace, moodle_user_id,
  binding_version, active)` validates namespace, positive identifiers, binding
  version, and explicit active state.
- `CourseAction` distinguishes `QUERY_COURSE` from
  `SYNC_COURSE_RESOURCE`.
- `AuthorizationDecision(allowed, reason_code, moodle_course_id, action,
  decided_at, policy_version, cache_state)` validates typed decisions and only
  permits `LIVE` or `FRESH_CACHE` cache provenance.

It also defines mock-injectable `Protocol` contracts for verified-principal
resolution, Moodle-binding resolution, and course authorization. There is no
resolver implementation and no permissive fallback. `require_dependency` fails
closed with `authorization_not_configured` when composition has not supplied a
dependency.

## Error semantics

Only stable, sanitized contract errors are public:

| Code | HTTP status |
| --- | ---: |
| `principal_required` | 401 |
| `moodle_binding_denied` | 403 |
| `course_access_denied` | 403 |
| `moodle_authorization_unavailable` | 503 |
| `authorization_not_configured` | 503 |

Their public payloads contain only a code and fixed message; they do not add
user attributes, tokens, Moodle responses, or credentials.

## Verification

Command run:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -q -p no:cacheprovider tests/deeptutor_integration/test_auth_contracts.py
```

Result: **11 passed in 0.46s**.

The test suite covers valid/invalid and expired principals; invalid, disabled,
and ambiguous bindings; action separation; timeout and missing-dependency 503
behavior; forged request headers/body; zero retrieval and LLM calls on denial;
the non-identity nature of internal service tokens; and validated decision/error
payloads. All calls are fakes or mocks. These tests do **not** prove live
authentication or Moodle authorization.

## Remaining blockers

### P0

1. A trusted original-credential verifier and deployment-approved issuer remain
   unselected; `VerifiedPrincipal` cannot be produced safely in production yet.
2. Principal-to-Moodle binding persistence, uniqueness, revocation, and audit
   implementation are not approved or implemented.
3. Moodle administrator approval/configuration is required for authorization
   functions/capabilities with verified enrollment and teacher course-context
   semantics.
4. The shared authorization policy is not wired before retrieval/LLM in
   `/deeptutor/query` or `/chat/grounded`; denial behavior is contract-tested
   only.

### P1

1. Thiện's PR #33 authorization/provenance integration remains absent from this
   branch and must be reconciled without assuming its behavior is active.
2. Quân/Streamlit must provide only presentation/session state; it cannot be a
   backend identity authority.
3. Live integration, cache/revocation timing, Moodle outage behavior, and
   route-level tests remain pending approved implementation and a test Moodle
   environment.

## Ownership and next approved work

- **Planner/deployment owner:** choose trusted authentication mechanism and
  issuer; approve binding storage and lifecycle policy.
- **Moodle administrator:** approve least-privilege, semantically sufficient
  enrollment/capability authorization surface.
- **Thiện:** align/land the shared query authorization and provenance contract.
- **Quân:** ensure frontend fields/session cannot be treated as verified backend
  identity.
- **Thọ:** wire approved injected dependencies only after the above decisions,
  then add route-level fail-closed tests.

No commit, push, merge, rebase, deployment, live Moodle call, or database/KB
write occurred.
