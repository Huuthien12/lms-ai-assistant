# Final live acceptance — end-to-end execution

## Actual execution outcome

An isolated writable SQL environment and local application startup were authorized and executed. The required Moodle administration identity was not available: both configured secure credentials returned `accessexception` for the read-only site-info capability check. Therefore the Moodle Login → Course → ACTIVE Document → Tutor → Quiz → Grading → Explanation → Flashcards → Progress → Mastery → Recommendations → Logout journey is **not executed**, rather than inferred from configuration or mocks.

| Journey stage | Automated evidence executed now | Live/manual result | Status |
| --- | --- | --- | --- |
| Identity, course ownership, logout | `test_verified_identity`, `test_learning_route_security`, `test_verified_learning_ui` | No approved Moodle identity | PENDING APPROVAL |
| ACTIVE publication, retrieval, stale/foreign source rejection | `test_verified_publication`, `test_verified_chat_integration`, `test_moodle_trust` | No real document mutation/read authorization | PENDING APPROVAL |
| Grounded Tutor | `test_grounded_chat`, `test_grounded_chat_router` | No approved provider/content request | PENDING APPROVAL |
| Quiz, deterministic grade, explanation | `test_verified_learning`, `test_quiz_lifecycle`, Quiz service/semantic tests, `test_explanation_service` | Isolated schema startup/restart passed; no Moodle-scoped Quiz may be created | PARTIAL |
| Wrong-answer review batches and four ratings | `test_verified_learning_integration`, `test_verified_learning`, `test_verified_learning_ui` | Isolated schema startup/restart passed; no Moodle-scoped batch may be created | PARTIAL |
| Progress, mastery, recommendations | Verified-learning integration/UI and `test_recommendation_service` | Isolated schema startup/restart passed; no approved learner evidence | PARTIAL |
| Restart persistence | Repository/fake coverage plus real schema restart | FastAPI/Streamlit restart passed; all business tables remain zero-row | PARTIAL |

The fresh vertical-flow test covers the safe equivalent sequence with isolated fixtures, including answer privacy, grading, evidence, explanation, post-Quiz card path, and mastery. It is automated integration evidence only. Historical P6 real-SQL evidence is recorded in `benchmark/reports/p6-implementation-2026-10-30/06-p6-final-acceptance.md` and is not claimed as fresh final-live execution.

## Execution-ready approved-environment procedure

1. Operator supplies an explicitly isolated test SQL database, approved Moodle test identities/course/document IDs, and provider/content budget; confirms no production target is in scope.
2. Record database backup/snapshot and initial schema before startup. Start FastAPI/Streamlit with only that isolated target; capture health endpoints.
3. Authenticate one student via `/auth/me`, select an authorized course and ACTIVE approved document, and ask one grounded question.
4. Generate a Quiz, intentionally submit a wrong answer, inspect private public DTO behavior, grade, and explanation. Capture only sanitized identifiers/screens.
5. Generate a post-Quiz review batch, verify idempotent repeat, rate AGAIN/HARD/GOOD/EASY, reload/re-authenticate, and confirm progress/mastery/recommendation stability.
6. Verify foreign-course denial with a separately approved test identity or preconfigured safe fixture; do not alter real enrollment merely for a negative case.
7. Log out, verify no stale private state, stop only the started processes, and clean/restore only the approved isolated database.

## Actual isolated-startup evidence

- Database: `codex_final_acceptance_20261031_a249d036f0ed`, verified absent before creation and never confused with `LMS_DeepTutor`.
- First clean startup: **FAIL**, safely isolated; SQL FK creation exposed router startup order dependency.
- Remediation: `f9411ef6` plus `tests/test_main_startup_schema_order.py`.
- Focused regression: **104 passed** (0 failures/errors) for startup order, Quiz lifecycle, verified learning, and integration.
- Corrected FastAPI startup, Streamlit startup, health checks, stop/restart, and post-restart zero-row schema check: **PASS**.
- Moodle-dependent workflow, persistence of actual learner evidence, and browser interaction remain blocked by missing authorized administration/user access.
- Acceptance cleanup passed: the named isolated database and its uniquely named local upload/log paths were removed after process shutdown and ownership verification.
