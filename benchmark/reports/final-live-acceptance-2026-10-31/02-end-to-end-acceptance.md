# Final live acceptance — end-to-end execution

## Actual execution outcome

No writable or authenticated real environment was authorized. Therefore the live journey Moodle Login → Course → ACTIVE Document → Tutor → Quiz → Grading → Explanation → Flashcards → Progress → Mastery → Recommendations → Logout is **not executed**, rather than inferred from configuration or mocks.

| Journey stage | Automated evidence executed now | Live/manual result | Status |
| --- | --- | --- | --- |
| Identity, course ownership, logout | `test_verified_identity`, `test_learning_route_security`, `test_verified_learning_ui` | No approved Moodle identity | PENDING APPROVAL |
| ACTIVE publication, retrieval, stale/foreign source rejection | `test_verified_publication`, `test_verified_chat_integration`, `test_moodle_trust` | No real document mutation/read authorization | PENDING APPROVAL |
| Grounded Tutor | `test_grounded_chat`, `test_grounded_chat_router` | No approved provider/content request | PENDING APPROVAL |
| Quiz, deterministic grade, explanation | `test_verified_learning`, `test_quiz_lifecycle`, Quiz service/semantic tests, `test_explanation_service` | No writable isolated SQL target | PENDING APPROVAL |
| Wrong-answer review batches and four ratings | `test_verified_learning_integration`, `test_verified_learning`, `test_verified_learning_ui` | No writable isolated SQL target | PENDING APPROVAL |
| Progress, mastery, recommendations | Verified-learning integration/UI and `test_recommendation_service` | No approved persisted learner evidence | PENDING APPROVAL |
| Restart persistence | Repository/fake coverage only | Starting application is write-capable and not authorized | PENDING APPROVAL |

The fresh vertical-flow test covers the safe equivalent sequence with isolated fixtures, including answer privacy, grading, evidence, explanation, post-Quiz card path, and mastery. It is automated integration evidence only. Historical P6 real-SQL evidence is recorded in `benchmark/reports/p6-implementation-2026-10-30/06-p6-final-acceptance.md` and is not claimed as fresh final-live execution.

## Execution-ready approved-environment procedure

1. Operator supplies an explicitly isolated test SQL database, approved Moodle test identities/course/document IDs, and provider/content budget; confirms no production target is in scope.
2. Record database backup/snapshot and initial schema before startup. Start FastAPI/Streamlit with only that isolated target; capture health endpoints.
3. Authenticate one student via `/auth/me`, select an authorized course and ACTIVE approved document, and ask one grounded question.
4. Generate a Quiz, intentionally submit a wrong answer, inspect private public DTO behavior, grade, and explanation. Capture only sanitized identifiers/screens.
5. Generate a post-Quiz review batch, verify idempotent repeat, rate AGAIN/HARD/GOOD/EASY, reload/re-authenticate, and confirm progress/mastery/recommendation stability.
6. Verify foreign-course denial with a separately approved test identity or preconfigured safe fixture; do not alter real enrollment merely for a negative case.
7. Log out, verify no stale private state, stop only the started processes, and clean/restore only the approved isolated database.
