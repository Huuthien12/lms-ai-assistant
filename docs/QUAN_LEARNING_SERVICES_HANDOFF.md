# Quân — learning services implementation handoff

Date: 2026-10-11 (Asia/Saigon)

`C2C | EXECUTED | QUAN_VERIFIED_LEARNING_SERVICES`

`QUAN_STATUS = BLOCKED`

Implementation and local regression are complete for the changes below. This is
not a claim of production-ready verified retrieval, completed UI integration, or
live SQL Server E2E. Shared authorization and provenance interfaces are absent
from this checkout; application activation remains blocked on Thiện's integration.

## A / S. Baseline and commit

- Implementation baseline branch: `quan/ai-integration`.
- Baseline HEAD: `c31b40ff2b3292d5834fb5da9c6eba1889816117`.
- Publication branch (2026-10-12): `codex/quan-verified-learning-services`.
  This document is included in the scoped implementation commit; its exact SHA
  is available from that branch's Git HEAD. Publication does not change the
  BLOCKED integration status. No merge or deployment is included.
- Existing untracked raw-provider/search-source modules, their tests and reports
  under `docs/reviews/` were preserved. DeepTutor submodule was not modified.

## B / C / M. Architecture and integration contract

`backend/services/ai/learning_context.py` defines immutable, strictly shaped
`LearningScope`, `LearningSource`, and `VerifiedLearningContext` DTOs. The name
does not confer trust: constructing/deserializing one, setting `verified`, or
matching identifiers is not authorization or provenance verification.

`LearningGenerationService` in `lms-dlu-demo/learning_generation.py` consumes:

1. A server-created scope with `owner_id` and canonical `course_id`.
2. Server-resolved `kb_id`, retrieval reference, retrieved text and source refs.
3. An injected synchronous `context_validator(scope, context) -> bool` supplied
   by the shared integration layer. Only literal `True` permits generation.

The validator must check genuine upstream issuance/receipt, current user/course
authorization, course–KB binding, and source lifecycle/provenance against trusted
state. It is called before provider invocation and again before persistence.
Missing validator, rejection, exception or empty sources prevents persistence;
initial rejection/empty sources makes zero provider calls. There is no raw KB
search or fallback to an unverified route. This callback is an adapter seam,
not an implementation of Thiện's receipt or policy.

Provenance defaults to `unverified`. Document/version/hash/chunk identities are
copied from supplied context, never synthesized from provider citations. There
is no competing auth policy, receipt issuer, ingestion or provenance verifier.

Public router factories accept `scope_dependency`; the quiz and learning routers
also accept `writer_dependency` for `/internal/*` writes. The shared FastAPI guard
must authorize each request and return `LearningScope`, resolving scope from the
stored resource for ID-only URLs. A writer dependency must actually authorize a
trusted service; hiding a route from OpenAPI is not protection.

When dependencies are omitted (as in current `main.py`), learning routes return
503 `learning_auth_not_configured`. Do not replace these defaults with permissive
lambdas in production. No student-supplied role, student ID, score or key is used
as authority. Legacy body/query `student_id` values are checked against scope.

Integration call surface:

```python
generation = LearningGenerationService(
    quiz_service, flashcard_service, quiz_repository, evidence_repository,
    context_validator=shared_context_validator,
)
quiz = await generation.generate_quiz(
    scope, context, topic="Python", question_count=5, difficulty="easy",
)
cards = await generation.generate_flashcards(
    scope, context, topic="Python", count=5, difficulty="easy",
)
```

The existing low-level `generate_grounded_*` and legacy prompt methods remain
internal provider adapters for compatibility. They do not independently authorize
users and must not be exposed as public verified-generation endpoints.

## D / E / F / G. Quiz

- Validator is static and no longer dereferences `self=None` during persistence.
- Validation bounds question count, options and content; rejects duplicate IDs,
  duplicate questions/options and invalid keys. Stored questions require IDs.
- Generation adapter assigns UUIDs on the server; public output retains them.
- Public projection explicitly allowlists question/option fields. Keys,
  explanations, raw context and nested metadata do not appear before submission.
- Trusted quiz context persists separately from the public payload. Generated
  personal quizzes enforce owner/course on reads and attempt creation.
- `GET /quizzes/{quiz_id}` reads persisted public content with scope checks.
- Submission checks stored attempt owner/course inside the transaction before
  grading/mutation; checks the quiz's course too. Client score/key fields are
  rejected at HTTP validation.
- MCQ grading uses stored keys with zero provider calls. Answers, evidence,
  mastery and submitted status are committed together or rolled back together.
- Existing lifecycle schema is retained: saved definition = created/trusted;
  `IN_PROGRESS` = presented; `SUBMITTED` = graded and reviewable. Repeated start
  returns the active attempt; repeated submit returns conflict.
- `quiz()` is a trusted server lookup; HTTP callers use `quiz_for_student()`.
  Context-less legacy quiz definitions remain course-shared server artifacts;
  existing attempts still have owner/course checks.

## H. Review / explanation

Review verifies attempt ownership/course and submitted state. For new artifacts
it returns the stored generation rationale, selected/correct option and persisted
source references for wrong/unanswered questions. This is the saved rationale,
not a newly generated personalized explanation or semantic citation validation.
It neither calls the provider nor changes the locked score. Old quizzes without
stored context return `explanation_status=unavailable`.

## I / J. Flashcards and evidence

- Registration now requires nonblank front/back and owner, and stores complete
  artifact JSON with context/source version data. Generated batches are atomic.
- Exact duplicate registration is idempotent; conflicting content fails.
- `GET /flashcards/{flashcard_id}` returns content only after owner/course checks.
- Reviews verify stored owner/course and preserve review-ID idempotency.
- Legacy rows with missing content are not fabricated: reads/reviews return
  `flashcard_context_unavailable` and require controlled re-generation/backfill.
- Quiz evidence references attempt/question and stored context through the quiz;
  card evidence references review/card and its persisted artifact.
- Flashcard ratings are explicitly learner self-reports, not verified correctness.

## K. Mastery / recommendations

Existing deterministic heuristic retained: quiz accuracy has 80% weight and
flashcard rating average 20% when both exist; the available component otherwise
has full weight. AGAIN/HARD/GOOD/EASY map to 0/0.4/0.75/1. Scope isolates evidence.
This is a heuristic, not an ML adaptive-learning claim.

Empty course progress returns an empty list. A requested topic without evidence
returns a null mastery score, zero evidence and LOW confidence. Recommendation
returns INSUFFICIENT_EVIDENCE with REVIEW_TOPIC/EASY_QUIZ and no provider call.
Existing rule decisions remain authoritative; optional LLM text cannot replace
action/ranking fields, although its prose is not semantically verified.

## L. Failures

Missing shared auth: 503. Forbidden owner/course: 403. Missing artifact: 404.
Repeated submission / conflicting artifact or review: 409. Invalid submissions:
422. Persistence failures: 503. Known codes are allowlisted so unexpected
validation exceptions cannot leak stored data. Provider failure/schema handling
continues to use controlled service errors, never fake successful artifacts.

## Persistence migration

`ensure_schema()` adds nullable columns only when missing:

- `dbo.QuizDefinitions.context_json NVARCHAR(MAX)`.
- `dbo.Flashcards.artifact_json NVARCHAR(MAX)`.

Existing rows remain intact; INSERTs name columns explicitly. Run schema setup
with the normal application migration/startup privileges before using new writes.
No live database migration was executed here. Validate these SQL Server changes
against both an empty database and a populated pre-migration database before
deployment; the transactional DB fake cannot prove engine-specific behavior.

## N. Files changed

- `.gitignore`: ignore local uv cache.
- `backend/services/ai/learning_context.py`: integration DTOs.
- `backend/services/ai/quiz_service.py`: validator, bounds and ID projection.
- `backend/services/ai/flashcard_service.py`: output size/count bounds.
- `backend/services/ai/recommendation_service.py`: explicit no-evidence result.
- `lms-dlu-demo/learning_access.py`: default denial and scope adapter.
- `lms-dlu-demo/learning_generation.py`: validated generation/persistence adapter.
- `lms-dlu-demo/quiz_lifecycle.py`: persistence, safe reads, scoped submissions.
- `lms-dlu-demo/learning_evidence.py`: complete cards, guards, atomic batches.
- `lms-dlu-demo/learning_workflow.py`: scoped review and recommendations.
- `tests/test_quiz_lifecycle.py`: updated storage and authenticated contracts.
- `tests/test_verified_learning.py`: 34 added contract/security/composition cases.
- `tests/ai/test_ai_evaluation_matrix.py`: explicit test-only scope dependency.
- `tests/ai/test_ai_integration_acceptance.py`: no-evidence contract.
- This handoff document.

## O / P / Q. Validation

Final command (local `.venv`, Python 3.10.22):

```powershell
.venv\Scripts\python.exe -m pytest tests -q --disable-warnings
```

Result: **1006 passed, 3 subtests passed, 27 warnings**, exit 0. Warnings include
FastAPI/Starlette deprecations. `git diff --check --ignore-submodules` passed.
The full command was rerun on 2026-10-12 before publication with the same result.
Tests ran outside Windows sandbox after async/HTTP tests stalled inside it.
No live LLM, Moodle, SQL Server or external retrieval was used by the new tests.

Coverage includes malformed provider output, recursive key leakage, deterministic
grading, owner/course spoofing, missing verifier/auth, empty context, revocation
before persist, atomic quiz/evidence rollback, card batch rollback, persistence
reload, review gating, no evidence and generation → submit → mastery composition.

Existing upload/DeepTutor write-auth and grounded retrieval regressions are part
of the successful full run. Shared #33/#34 principal/course/provenance acceptance
cannot be claimed: exact upstream implementations/tests are absent locally.
DeepTutor's separate submodule test suite was not run or modified.

## R / T. Remaining blockers and handoff criteria

1. Thiện must supply shared scope/writer dependencies and genuine context receipt
   validation; agree the adapter against the exact upstream types and revisions.
2. Wire authorized retrieval → generation service → API/UI in the application.
   Generation remains an internal service seam until that dependency exists.
3. Execute SQL Server migration/rollback/concurrency checks against real storage.
4. Run actual #33/#34 shared-security regressions and live course → generation →
   submit → grading → mastery E2E after integration.
5. Product UI integration is not completed here; Gemini/benchmark remain P2.

`QUAN_STATUS = BLOCKED` until these integration and verification requirements pass.
