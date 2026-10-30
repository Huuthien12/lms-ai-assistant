# Legacy Quiz fixture regression — 2026-10-30

## Result

The nine legacy Quiz regressions are fixed by updating deterministic test fixtures only. Production validation was not modified by this repair.

## Root causes

The prior broad regression (`p5-full-20261030-180302.junit.xml`) collected 273 tests: 264 passed and nine failed. All nine reached `QuizService.validate_and_parse_quiz()` with outdated fixture shapes.

1. The two semantic-grounding fixtures used deprecated cloze-shaped, two-option responses instead of an evidence-first response with natural learner-facing text, four distinct A-D options, and bound `evidence_id` / `answer_span_id` values.
2. Seven Quiz-service tests shared an A/B mock response. Structural validation correctly rejected it before the intended semantic, privacy, source-snapshot, or observability assertion could run.
3. The count fixture initially supplied one source unit for twenty questions. The validator correctly rejected insufficient distinct candidate bindings. It now supplies twenty exact, distinct evidence literals and lets the mock copy the generated candidate bindings.
4. Source-snapshot assertions had stale assumptions: an evidence-first generation without caller sources is not a valid generation path, and a single source dictionary is persisted as its selected one-item source list.

## Fixture contract comparison

| Property | Old fixture | Updated fixture |
| --- | --- | --- |
| Options | Two A/B options | Exactly four distinct A-D options |
| Question text | Deprecated cloze wording | Natural learner-facing Vietnamese question |
| Correct answer | Unbound fixture literal | Exact locked answer-span literal |
| Grounding | `grounding_evidence` only | Candidate-bound `evidence_id` and `answer_span_id` |
| Negative semantic case | Could fail structurally first | Reaches unsupported-evidence validation |
| Public result | Historically asserted | Still asserts answer keys, explanations, evidence, and source metadata are excluded |

The invalid fixtures remain intentionally invalid where a structural rejection is the behavior under test. The semantic-rejection fixture now passes structure and reaches the unsupported-evidence branch as intended.

## Files changed

- `tests/ai/test_quiz_semantic_grounding.py:41-146`: adds a reusable evidence-first fixture and updates the former cloze acceptance case; preserves a negative source-binding case.
- `tests/ai/test_quiz_service.py:19-35`: replaces the shared A/B mock with a valid four-option, bound evidence-first response.
- `tests/ai/test_quiz_service.py:170-175`: gives grounded tests a real source block and approved source metadata.
- `tests/ai/test_quiz_service.py:261-301`: makes the twenty-question mock derive its exact answer bindings from `quiz_candidates`.
- `tests/ai/test_quiz_service.py:314-333, 494-525`: corrects source ownership/snapshot setup without weakening validation.

`backend/services/ai/quiz_service.py` was not modified by this repair. It remains modified in the pre-existing dirty working tree; this fixture-only change neither alters nor resets that work.

## Verification

| Check | Result |
| --- | --- |
| AST syntax parse for both changed test modules | PASS |
| `git diff --check` for the changed test modules | PASS |
| Exact historical nine-test selection | 9 passed, exit code 0 |
| Eleven-module P5 regression | 273 passed, 0 failed, 0 errors, 0 skipped; exit code 0 |

Fresh JUnit evidence:

- Focused: `benchmark/reports/p5-final-release-2026-10-30/regression/legacy-quiz-fixtures-focused-20261030-final.junit.xml`
- Full: `benchmark/reports/p5-final-release-2026-10-30/regression/p5-full-legacy-quiz-fixtures-20261030.junit.xml`

The full run emitted 29 dependency deprecation warnings (FastAPI/Starlette lifecycle and TestClient/httpx); no warning was treated as a test failure.

## Remaining blockers

None for this fixture-regression gate. No database, Moodle account, UI, provider configuration, launcher, Git history, staging, commit, or push was changed. Any final security audit and Git publication remain separate gates.
