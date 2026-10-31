# P6 final acceptance

Date: 2026-10-31
Repository: `D:\DeepTuTor-verified`
Baseline: `6a4d0107aa031b0e71a9c19153bf4c736397c6f6`

## Completed implementation

- P6-A0 persists `trusted_provenance` v1 per Quiz question, derived solely from verified context source bindings.
- P6-A1 adds database-unique ReviewBatch attempt ownership, short serializable reservations, five-minute leases, FAILED retry release, and one atomic transaction for Flashcards, artifact bindings, batch mappings, and READY.
- `POST /learning/attempts/{attempt_id}/review-flashcards` accepts only the attempt path ID. It derives ownership, current course access, submitted/graded wrong answers, chapter mappings, and fresh ACTIVE context server-side.
- `LearningGenerationService.prepare_flashcards()` creates only fully validated, grounded registrations. Normal Flashcard generation still persists through its original `register_flashcards()` path; post-quiz publication uses only `publish_review_batch()`.
- The Streamlit grade result now exposes **Ôn tập câu sai bằng Flashcard** for an incorrect attempt and reuses the existing AGAIN/HARD/GOOD/EASY card-review controls.

## Security properties verified

- No client topic, course, source, answer, or answer key is accepted by the review endpoint.
- Foreign owners, unsubmitted attempts, legacy/ambiguous provenance, revoked enrolment, deleted/inactive chapters, and stale version/hash provenance fail closed before generation.
- Per-question chapters may differ; each is freshly re-authorized and retrieved, then all validated cards are committed atomically.
- Active competing reservations return PENDING. READY retries return the existing batch without another generation or duplicate cards.
- Provider/schema failure releases the reservation as FAILED and creates no partial cards or mappings.

## Fresh executable evidence

| Scope | Result | JUnit artifact |
| --- | ---: | --- |
| `prepare_flashcards()` zero-write and normal persistence contract | 2 passed | `p6-preparation-contract.junit.xml` |
| HTTP endpoint matrix: success/idempotency, all-correct, owner/access, revoked enrolment, legacy/ambiguous/stale provenance, inactive chapter, provider failure, PENDING, and multi-chapter | 11 passed | `p6-post-quiz-http-matrix.junit.xml` |
| Disposable SQL Server transaction, rollback, lease, uniqueness and overlapping-publication matrix | 18 passed | `p6a1-real-sql-release.junit.xml` |
| Required eleven-module P5 regression | 286 passed | `p6-p5-eleven-module-release.junit.xml` |
| Verified-learning Streamlit UI suite | 18 passed | `p6-ui-release.junit.xml` |

The SQL fixture used only same-run `codex_acceptance_<uuid>` databases and performs same-run cleanup. `LMS_DeepTutor`, Moodle production data, and Docker data were not used or modified.

## Release audit

The Git candidate is limited to the P6 implementation files, focused tests/fake, SQL acceptance test, and this sanitized report. JUnit XML, virtual environments, runtime/test temporary directories, private evaluation material, `.env`, protected local credential artifacts, logs, and unrelated untracked artifacts are excluded. Final staged-diff and secret scan results are recorded after staging/commit.

## Pending separate operational gate

Production schema deployment and live Moodle acceptance are intentionally not performed by this change. They remain deployment approval work, not a source or feature-branch blocker.

## Status before publication

- P6 CODE: PASS
- P6 AUTOMATED/HTTP: PASS
- P6 REAL SQL: PASS
- P6 UI: PASS
- P6 SECURITY AUDIT: PENDING FINAL STAGED SCAN
- P6 FEATURE PUSH: PENDING FINAL STAGED REVIEW
- P6 LIVE ACCEPTANCE: PENDING DEPLOYMENT APPROVAL
