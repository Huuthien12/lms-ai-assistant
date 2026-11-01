# DeepTutor Verified — UI Release Audit & Packaging

**Date:** 2026-11-01
**Candidate branch:** `codex/verified-ui-reference-completion-20261101`
**Baseline inspected:** `origin/project-main` at `6b3b7eb5e21ee1acff190a19cc82d58f19160331`

## Decision

**READY FOR OPERATOR-APPROVED COMMIT.** The explicit UI-release allowlist was security-reviewed and staged only after fresh regression evidence. This audit does not authorise a commit, push, merge, deployment, Moodle mutation, or production SQL change.

Final Live Acceptance remains **PARTIAL / production NO-GO**.

## Branch and dependency assessment

- The candidate branch points at `65491a5f`, four commits ahead of `origin/project-main`; its merge base is `6b3b7eb5`.
- Those existing commits are Final-Acceptance/schema dependency history (`f9411ef6`, `1d562e8f`, `bbdd99a1`, `65491a5f`), not newly staged UI content. They are already part of branch history and are not re-packaged by this worktree commit.
- The index was empty before packaging. No checkout, reset, stash, clean, merge, or history rewrite was run.
- `lms-dlu-demo/app.py:50–52` was verified unchanged: it still invokes `render_verified_learning(FASTAPI_URL)` and `st.stop()`.

## Explicit inclusion allowlist

| File | Reason |
| --- | --- |
| `DESIGN.md` | project-owned DeepTutor visual-system guidance |
| `lms-dlu-demo/ui/components.py` | escaped verified shell/header/empty-state components |
| `lms-dlu-demo/ui/theme.py` | reference-driven responsive, focus, form, Quiz, Flashcard styling |
| `lms-dlu-demo/verified_learning_ui.py` | verified Streamlit UI only; uses real API data and preserves existing guarded actions |
| `lms-dlu-demo/verified_identity_router.py` | authenticated self-only read-only profile projection |
| `lms-dlu-demo/verified_learning_router.py` | reauthorized ACTIVE-publication overview projection |
| `tests/test_verified_identity.py` | profile identity/fail-closed/public-field exclusion tests |
| `tests/test_verified_learning_integration.py` | overview isolation, no-write, and capability tests |
| `tests/test_verified_learning_ui.py` | UI workflow, state cleanup, escaping, profile/overview assertions |
| `tests/ui_browser_fixture.py` | loopback-only synthetic browser fixture; never imported by production |
| `benchmark/reports/ui-polish-full-2026-11-01/01-ui-polish-full-implementation-and-verification.md` | baseline reference map and screenshot evidence |
| `benchmark/reports/ui-polish-full-2026-11-01/02-reference-completion-addendum.md` | completion audit and Image2Code decision |
| `benchmark/reports/ui-polish-full-2026-11-01/verified-ui-release-audit-*.junit.xml` | fresh machine-readable regression evidence |
| this report | release allowlist, exclusions, and staged audit record |

## Explicit exclusions preserved in the worktree

- `backend/services/ai/quiz_service.py` and `tests/ai/test_quiz_service.py`: unproven Quiz option-A prompt experiment.
- `lms-dlu-demo/learning_generation.py`, `tests/test_verified_learning.py`, demo quick-login changes, and unrelated P5–P8 work: outside this UI/read-only API release.
- Final-Acceptance reports/runtime directories, `.acceptance-logs/`, `.playwright-cli/`, `.pytest-*`, `.test-tmp-*`, `audit-inputs/`, `deeptutor-venv-backup/`, virtual environments, cache/runtime directories, broad benchmark inputs/results, and historical reports: not source-release content.
- The duplicate `benchmark/reports/verified-ui-reference-completion-2026-11-01/` report remains untracked and excluded because the authoritative UI reports above already carry the same evidence.
- Browser screenshots live outside the repository and are not release candidates.

## Security and contract audit

- `/auth/me/profile` receives the same verified authorizer dependency as `/auth/me`; it projects only the current binding’s Moodle ID, authorised-course count, and `VERIFIED` state. It has no request body and no write path.
- `/learning/courses/{course_id}/overview` calls `access.scope(course_id)` before exposing data, counts only `publications.documents(scope)` (ACTIVE records), and exposes document management only after the existing `SYNC_COURSE_RESOURCE` capability action succeeds.
- Tests prove foreign-course `403`, unauthenticated `401`, self-profile fail-closed behaviour, no `owner_ref`/bearer output, no learner activity/KPI/answer-key response fields, and no mutation of the isolated repository state.
- No change touches Quiz validation, grading, attempt persistence, ReviewBatch, ledger/database contracts, provider selection, Moodle request format, or DPAPI quick login.
- `unsafe_allow_html` additions escape server-provided title/message/course text before interpolation.

## Secret and artifact scan

The exact allowlist was scanned for private-key blocks, AWS/GitHub/Slack/OpenAI credential signatures, and DPAPI markers. No credential, token value, private key, DPAPI blob, or binary file was found. The only `DPAPI` hits are explanatory documentation stating that credentials are not exposed.

## Fresh regression evidence

| Suite | Result | Unique test cases | Purpose |
| --- | --- | ---: | --- |
| `verified-ui-release-audit-focused.junit.xml` | 69 passed, 0 failed/error/skip | 69 | identity, verified integration, UI flow |
| `verified-ui-release-audit-ui-baseline.junit.xml` | 62 passed, 0 failed/error/skip | 62 | preserved UI baseline + verified-learning compatibility |
| `verified-ui-release-audit-security.junit.xml` | 50 passed, 0 failed/error/skip | 50 | identity, integration, lecturer contract |

The three executions cover **112 unique test cases**. Pairwise overlap is 22 (focused/baseline), 47 (focused/security), and 0 (baseline/security); test totals must not be added as if independent.

`py_compile` completed for all allowed Python source/tests. `git diff --check` passed before staging.

## Staged-diff audit

Only the 16 listed paths were staged individually; no broad `git add` command was used. The staged set exactly matched the allowlist (no missing or unexpected path). `git diff --cached --check` passed after removing three Markdown hard-break whitespace findings. The staged credential-signature scan found no high-confidence secret and the staged binary scan passed.

## Next operator action

Review the staged diff, then explicitly authorise a normal commit (and, separately, any push/PR). Do not approve production deployment as part of this UI release.
