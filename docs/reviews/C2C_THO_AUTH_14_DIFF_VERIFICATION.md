# C2C THO-AUTH-14 — Authentication Contract Independent Diff & Test Verification

## Verdict

**READY_TO_COMMIT** for the scoped AUTH-13 contract groundwork only. This is
not approval to enable production authentication or Moodle authorization.

## 1. Workspace and Git inspection

- Repository identity: **DeepTutor LMS AI Assistant** (project README)
- Repository root: `C:\Users\PHUC THO\Documents\ChatGPT\lms-ai-assistant`
- Branch: `tho/moodle-download-security` (expected branch)
- HEAD: `0139f8e177a35f8192b8ecb715332f8a3e45a225`
- `git rev-parse --is-inside-work-tree`: `true`

The earlier “not a work tree” result was reproduced as an execution-sandbox
permission limitation: a sandboxed Git process could not change into the
sibling repository. Read-only Git inspection outside that sandbox succeeded;
no Git configuration, environment file, or repository metadata was changed.

`git status --short` reports only untracked paths. Both tracked and staged
diff inventories are empty. The untracked inventory is:

| Path | Classification |
| --- | --- |
| `deeptutor_integration/auth_contracts.py` | Expected AUTH-13 source file |
| `tests/deeptutor_integration/test_auth_contracts.py` | Expected AUTH-13 test file |
| `docs/reviews/C2C_THO_AUTH_13_EXECUTION.md` | Expected AUTH-13 handoff |
| `docs/reviews/C2C_THO_AUTH_10_FEASIBILITY.md` | Pre-existing report; preserved |
| `docs/reviews/C2C_THO_AUTH_11_DECISION.md` | Pre-existing report; preserved |
| `docs/reviews/C2C_THO_AUTH_12_SHARED_AUTH_CONTRACT.md` | Pre-existing report; preserved |

The three expected AUTH-13 files were independently inspected with
`git diff --no-index /dev/null <path>`. No additional application or test
file is proposed by this task.

## 2. Contract validation review

### Guarantees implemented by the dataclasses

- `VerifiedPrincipal` is `@dataclass(frozen=True)`, rejects blank `subject` and
  `issuer`, requires timezone-aware timestamps, and requires expiry strictly
  after authentication. `require_active` explicitly rejects an expired
  principal with `principal_required` (401).
- `MoodleUserBinding` is frozen, rejects non-positive/non-integer Moodle user
  IDs and binding versions, and makes `active` an explicit boolean. Its
  `require_active` path rejects disabled bindings with
  `moodle_binding_denied` (403).
- `CourseAction` has distinct `QUERY_COURSE` and `SYNC_COURSE_RESOURCE`
  values. `AuthorizationDecision` accepts only a typed action and cache state,
  validates its boolean `allowed` field, positive course ID, reason code,
  decision timestamp, and policy version. `CacheState` accepts only `LIVE` or
  `FRESH_CACHE`.
- Resolver/authorizer dependencies are `Protocol` callables and have no default
  implementation. `require_dependency(None)` fails closed with
  `authorization_not_configured` (503).
- Fixed public error payloads cover 401/403/503 and contain only a stable code
  and generic message. No contract error interpolates a token, Moodle response,
  URL, or identity profile.

### Behavior demonstrated only by mocks

- The test fakes show that a resolver which rejects forged client headers/body
  results in no retrieval or LLM call.
- The action-separation test demonstrates a mock policy may allow query while
  denying synchronization.
- Ambiguous binding and Moodle unavailability are represented by fail-closed
  fake errors.

These mocks do not prove a real credential verifier, real binding store,
Moodle enrollment/capability behavior, or route-level enforcement. No
Streamlit role, client header, internal API key, or Moodle service token is
implemented as a verified principal.

## 3. Scope and security verification

Object hashes of the working copy match `HEAD` for all protected files:

- `deeptutor_integration/api.py`
- `lms-dlu-demo/main.py`
- `lms-dlu-demo/grounded_chat_router.py`
- `lms-dlu-demo/moodle_adapter.py`

There is no tracked configuration, login/session, database, service, or
Moodle-adapter modification. The newly inspected module has no external
network, database, Moodle, IdP, or route dependency. No live authentication or
authorization path was activated.

No MAJOR or BLOCKER defect was found in the scoped diff. The only observation
is Git's normal Windows line-ending warning for the new files; it does not
indicate content or security drift.

## 4. Test verification

Command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; python -m pytest -q -p no:cacheprovider tests/deeptutor_integration/test_auth_contracts.py
```

Result: exit code **0**; **11 passed in 0.41s**. This reproduces the eleven
AUTH-13 focused tests. Coverage is mock-only and does not contact Moodle, a
database, an identity provider, or any external service.

## 5. Remaining blockers and required future work

1. **P0:** Deployment/Planner must select a trusted original-credential
   verifier and issuer before `VerifiedPrincipal` can be created in production.
2. **P0:** Principal-to-Moodle mapping persistence, uniqueness, audit, and
   revocation policy require approval and implementation.
3. **P0:** Moodle administrator must approve a least-privilege authorization
   API/capability surface whose enrollment and teacher-permission semantics are
   sufficient.
4. **P0:** Shared fail-closed policy must be injected before retrieval/LLM in
   `/deeptutor/query` and `/chat/grounded`, with route-level tests.
5. **P1:** Reconcile Thiện's PR #33 contract work and keep Quân's frontend
   session state outside the trusted backend identity boundary.

No fix is required for committing the narrowly scoped files. The blockers above
prohibit treating this commit as live-authentication authorization approval.
