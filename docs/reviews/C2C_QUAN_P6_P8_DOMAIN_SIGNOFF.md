# C2C | QUAN | P6-P8 LEARNING DOMAIN SIGNOFF

Execution date: 2026-10-15 (Asia/Saigon).

This lane was created from the required team baseline after fetching `origin`.
The evidence levels in this report are deliberately separate: automated code
tests do not prove the state of the historical Moodle/SQL records.

| Item | Result |
|---|---|
| Repository | `Huuthien12/lms-ai-assistant` |
| Branch | `codex/quan-p6-p8` |
| Required base | `fd9cef2fdf46f16ab86d718500219a1ccc42b809` |
| Verified `origin/project-main` | `fd9cef2fdf46f16ab86d718500219a1ccc42b809` |
| Final SHA | Record in the execution response; a commit cannot contain its own SHA. |
| Tracked files in this lane | `tests/test_verified_learning_integration.py`; this report |
| Production code changed | No |
| Database migrations | None |
| Historical Quiz regenerated or resubmitted | No |

## Executed verification

| Check | Current-run result |
|---|---|
| Focused Quiz/Flashcard/grading/mastery/lifecycle/integration suite | **PASS: 346 passed**, exit 0 |
| Full backend/domain suite | **PASS: 1289 passed + 16 subtests**, exit 0 |
| Streamlit UI suite | **BLOCKED_BY_DEPENDENCY**: 7 collected cases could not run because `streamlit` is absent; repeated install attempts were blocked by the package registry while downloading the large UI dependencies. |
| Full collection with UI included | **BLOCKED_BY_DEPENDENCY** at `tests/test_verified_learning_ui.py`; no product assertion failed. |
| Opt-in SQL acceptance | **BLOCKED_BY_ENVIRONMENT**: both `empty` and `populated_legacy` modes failed before database creation with SQL Server connection error `08001` at `localhost`. No test or production database was modified. |
| Live Moodle / historical Quiz | **NOT_VERIFIED**: no personal Moodle credentials or live SQL configuration are present in this checkout. |
| Dependency consistency | **PASS: 60 installed packages compatible** |
| Diff whitespace check | **PASS** |

The Python environment supplied with the checkout is Python 3.10 while the
code uses `enum.StrEnum`. Tests were executed with a process-only compatibility
shim stored under ignored `.venv`; source behavior was not changed. The full
backend/domain run excluded only `tests/test_verified_learning_ui.py` because
Streamlit was unavailable.

## Historical Phase 6 Quiz boundary

The master assignment describes one Student A (`user6`) / `INT1339` Quiz with
five questions, one submitted attempt, five answers, two correct, three
incorrect, score 40, mastery 40 / WEAK / MEDIUM / evidence 5, and ACTIVE
`Chuong 1.pdf` provenance. None of those live row counts or source facts were
queried in this run. They remain **NOT_VERIFIED**, and this report does not
promote the assignment statement into execution evidence.

The new automated regression reproduces the same cardinality and score shape
with synthetic data: one attempt, five distinct persisted answers, two correct,
three incorrect, 40 percent, five evidence events, and deterministic mastery
40 / WEAK / MEDIUM / evidence 5. It also proves that retrying submission returns
the controlled duplicate response without changing persisted state. This is
code-path evidence only; it is not evidence about the historical records.

## P6 findings

- **Transaction/cardinality:** code and synthetic integration PASS. Submission
  validates all question/option ownership before grading, writes answers,
  evidence, mastery inputs, and submitted state in one transaction, and rolls
  back on failure. The exact live submission/attempt/answer counts remain
  NOT_VERIFIED.
- **Deterministic grading:** PASS. The server grades against the stored private
  key. Client-supplied correctness, correct answer, score, and explanation
  fields are rejected. Provider calls are asserted to remain zero during
  grading. Missing answers are persisted as unanswered/incorrect; foreign extra
  questions are rejected atomically.
- **Score/mastery consistency:** synthetic 2 + 3 produces 40 percent and the
  expected deterministic mastery tuple. The historical 40 percent row and its
  owner/course scope remain NOT_VERIFIED.
- **Semantic key validity:** structural validity PASS: every trusted key must
  identify an option belonging to its question. Historical semantic support is
  **NOT_VERIFIED** because it requires securely comparing each private key and
  option set to the exact saved ACTIVE `Chuong 1.pdf` chunks. General Python
  knowledge and the synthetic provider fixture are not substitutes for that
  source review.
- **Pre-submit exposure:** PASS in public projection tests. Correct keys,
  rationale/explanation, answer-key aliases, and raw context are absent.
- **Evidence/mastery isolation:** code and synthetic tests PASS for stored
  owner/course scope, cross-user/course denial, and five evidence events. The
  historical absence of Course3 evidence remains NOT_VERIFIED.

## Review fallback classification

The authorized review endpoint first requires a submitted attempt, reauthorizes
the stored owner/course scope, and revalidates the saved context against the
current ACTIVE publication. It initializes each result as `unavailable`.

There are two code paths that keep that status:

1. Current authorization or ACTIVE context revalidation fails. No explanation
   provider call occurs.
2. Context is ACTIVE, but explanation generation or explanation schema
   validation raises the controlled `ValueError` path.

The Streamlit text `Ngữ cảnh đã thay đổi hoặc chưa có giải thích.` is therefore
a truthful combined fallback, but it does not identify which of those two paths
occurred. The synthetic inactive-source test proves that a retired source leaves
the already-persisted deterministic score intact, returns unavailable review,
and performs zero provider calls. This does not affect grading or expose a key.
Explanation completeness is unavailable. Current provenance is unavailable in
the inactive-context branch; in the provider-failure branch, the context passed
ACTIVE verification but the response still omits an explanation/source bundle.

The root cause of the historical UI occurrence is **NOT_VERIFIED** without its
review payload and server evidence. It is not a code-side grading or security
blocker. It remains a live acceptance blocker for historical explanation
completeness and current provenance until Thiện distinguishes the two branches.

`C2C | CHECKPOINT | QUAN_P6_LEARNING_VERIFIED`

- Historical submission count / one attempt / five answers: NOT_VERIFIED live;
  equivalent synthetic shape PASS.
- Deterministic server grading: PASS; LLM used for grading: NO; trusted private
  server key: PASS; synthetic 2/3 score and mastery consistency: PASS.
- Historical semantic-key support from ACTIVE source: NOT_VERIFIED.
- Pre-submit key exposure: PASS (no exposure).
- Review fallback: code paths classified; grading/security unaffected;
  historical root cause and explanation/provenance acceptance remain live work.
- ACTIVE-only and cross-course evidence controls: PASS code-side; historical
  `Chuong 1.pdf` / no-Course3 rows: NOT_VERIFIED.
- Production fix: none required by current automated evidence. Regression tests
  added; focused suite PASS.

## P7 abuse/security findings

- Forged client `correct_answer`, correctness, score, and explanation fields:
  rejected with 422 before mutation.
- Option/question ownership, foreign question, duplicate answer, missing answer,
  and extra answer behavior: covered by grading/lifecycle/integration tests.
- Cross-user and cross-course start/submit/review/history/progress access:
  denied before provider or persistence side effects.
- Duplicate submit and retry after an uncertain response: controlled 409 with
  no duplicated answers/evidence.
- Review before submit: controlled 409.
- Stale or later-inactive source: no current explanation/provider access;
  historical deterministic grade remains readable and unchanged.
- Partial persistence failure: rollback PASS in unit/fake repository tests. The
  real SQL rollback matrix could not be re-executed because SQL Server was not
  available in this environment.
- Malformed persisted binding: sanitized 503; the injected marker does not
  appear in the response and grading/provider paths are not reached.
- Malformed Quiz and Flashcard provider output and provider timeout: controlled
  502 with no trusted artifact persistence.
- Public serialization/key leakage: PASS in integration tests; no live key or
  hidden answer identifiers were printed during this review.

`C2C | CHECKPOINT | QUAN_P7_LEARNING_SECURITY`

Forged-client, cross-user/course, duplicate-submit, stale-context, malformed
payload/provider, and leakage controls PASS in automation. Transaction rollback
PASSes code/unit coverage; current-run real SQL rollback is
BLOCKED_BY_ENVIRONMENT. No P0/P1 defect was confirmed.

## P8 handoff and live matrix for Thiện

Thiện should use authorized, read-only access to the existing historical Quiz.
Do not regenerate or resubmit it.

1. Confirm exactly one successful historical submit from HTTP/application audit
   evidence. Database cardinality alone cannot prove the HTTP request count.
2. Confirm one `QuizAttempt`, five distinct `QuizAnswers`, and the submitted
   state for Student A / `INT1339`, without displaying selections or private
   keys.
3. Recompute aggregate correctness from persisted selections and the private
   server key in a secure session; record only `2 correct`, `3 incorrect`, and
   `40.0%` or the mismatch classification.
4. For each question, compare question/options/private correct option to the
   exact five saved source chunks from the expected ACTIVE `Chuong 1.pdf`.
   Record supported/not-supported and root-cause category without exporting the
   key or hidden answer IDs.
5. Confirm the artifact and all evidence/mastery rows are scoped only to
   `user6` / `INT1339`, contain no Course3 evidence, and yield mastery 40 / WEAK
   / MEDIUM / evidence 5.
6. Invoke authorized review only. Capture `explanation_status`, whether current
   ACTIVE revalidation succeeds, whether the provider is called, and whether a
   source bundle is returned. This distinguishes context lifecycle failure from
   explanation/provider failure.
7. Run the live Flashcard matrix after automation is green: ACTIVE-only source,
   strict/partial/malformed/duplicate/timeout cases, persistence after relogin,
   cross-user/course denial, review idempotency, and transaction rollback.
8. Re-run `tests/test_verified_learning_ui.py` with Streamlit installed and the
   opt-in SQL acceptance with the ignored SQL environment file.

No new live Quiz is required because no production grading/generation fix was
made. Preserve the historical Quiz for the read-only investigation. If a future
semantic generation or key-mapping defect is fixed, create a separate new Quiz
for post-fix acceptance rather than rewriting the historical record.

`C2C | CHECKPOINT | QUAN_P8_DOMAIN_SIGNOFF`

- Base: `fd9cef2fdf46f16ab86d718500219a1ccc42b809`.
- Final SHA: supplied with the final execution receipt.
- Files: integration regression coverage plus this handoff; no production code
  or migration.
- Current exact execution: focused 346 passed; full backend/domain 1289 passed
  + 16 subtests; 7 Streamlit UI cases blocked by missing dependency; 2 SQL modes
  blocked before database creation; live Moodle NOT_VERIFIED.
- Quiz, Flashcard, grading, review, persistence, mastery, and security:
  code-side PASS within the executed suites and limitations stated above.
- Confirmed defects: none. Environment blockers: Streamlit package download,
  local SQL Server/configuration, and live Moodle credentials/data access.
- Safe to merge: **YES for this tests/docs-only lane after final diff/test
  checks**. Live acceptance required: **YES**. Production readiness: **NO until
  Thiện completes the live matrix**.
