# C2C THIEN-DEEPTUTOR-14 — Ledger V2 Independent Diff & Test Verification

## 1. Workspace and Git

- Workspace root: `D:\DeepTuTor` (VERIFIED).
- Branch / HEAD: `thien/kb-retrieval-security` / `0b09fc9f810a71e425c25a550be621991b4af3ba` (VERIFIED).
- Upstream: `origin` is `https://github.com/Huuthien12/lms-ai-assistant.git` for fetch and push.
- Staged changes: none.
- Unstaged tracked changes: `deeptutor_integration/contracts.py`, `deeptutor_integration/document_normalizer.py`, `deeptutor_integration/moodle_ingestion_ledger.py`.
- Untracked implementation test: `tests/test_moodle_ingestion_ledger_v2.py`.
- Untracked reports: `C2C_THIEN_DEEPTUTOR_09_VERIFICATION.md`, `C2C_THIEN_DEEPTUTOR_11_LEDGER_VERIFIER_CONTRACT.md`, `C2C_THIEN_DEEPTUTOR_12_UNIFIED_SECURITY_CONTRACT.md`, and `C2C_THIEN_DEEPTUTOR_13_EXECUTION.md`. These are preserved; they are not application changes.

No unexpected application or test files were found beyond the stated Ledger V2 scope. This report is the only new file made by this review.

## 2. Changed-file inventory and scope

| File | Scope finding |
|---|---|
| `deeptutor_integration/contracts.py` | Adds optional `NormalizedDocument.artifact_sha256`; existing direct V1 fixtures remain valid. |
| `deeptutor_integration/document_normalizer.py` | Adds UTF-8 Markdown artifact hash while preserving original byte hash behavior. |
| `deeptutor_integration/moodle_ingestion_ledger.py` | Adds isolated V2 types/persistence after unchanged V1 implementation. |
| `tests/test_moodle_ingestion_ledger_v2.py` | Adds focused V2 contract tests. |
| `docs/reviews/C2C_THIEN_DEEPTUTOR_13_EXECUTION.md` | Execution handoff only. |

`lms-dlu-demo/moodle_ingestion_router.py`, `grounded_chat_router.py`, provider/CLI code, and authentication code have no diff. No V2 class has a production caller; CodeGraph shows V2 callers are its tests. Therefore no secure retrieval activation or production ingestion wiring was added.

## 3. Diff verification findings

| Requirement | Status | Evidence / finding |
|---|---|---|
| V2 isolated from V1 production behavior | PASS | V1 remains at `MoodleIngestionLedger` with the same path/methods (`moodle-ingestion-index.json`, `contains`, `record`, `mark_deleted`). V2 uses a separate `moodle-ingestion-ledger-v2.json` path and has no production router caller. |
| V1 public method/file compatibility | PASS | Existing class code is unchanged; focused V1 regression test passes. |
| Original source hash | PASS | `source_sha256()` still hashes input bytes (`document_normalizer.py:32-35`). |
| Normalized artifact hash | PASS | `artifact_sha256()` hashes `markdown.encode("utf-8")` after line-ending normalization; Unicode/newline test reproduces this. |
| Immutable version not filename-derived | PASS | V2 requires caller-supplied `document_version_id`; storage identity is namespace/course/KB/document/version. Filename is absent from V2 identity. |
| Idempotent PENDING / conflicting reuse | PASS | Same immutable evidence returns existing record; same identity with changed immutable evidence returns `ledger_v2_conflict` (`create_pending`). |
| PENDING publication evidence | PARTIAL | Empty manifest/ref fails via ACTIVE model validation. However manifest entries are not checked for duplicate `chunk_id`/`source_ref`, and completeness cannot be established without upstream provider evidence. |
| Invalid lifecycle transitions | PASS | PENDING-only publish/fail and ACTIVE-only supersede/delete are enforced with fail-closed errors. |
| One ACTIVE version per logical document/KB | PASS for single-process state | `publish()` refuses a second ACTIVE logical identity until the old version is superseded. |
| Corrupt/mismatched state | PASS | Schema/JSON/key mismatch produces `ledger_v2_unavailable` (503). |
| Atomic local replacement failure | PASS for tested failure mode | Write uses temp file then `Path.replace`; test patches replacement and verifies prior file reloads unchanged. |
| V1 promotion | PASS | V2 reads only its own separate file. Existing V1 records are not imported/promoted. |

## 4. Security edge-case matrix

| Edge case | Classification | Evidence / impact |
|---|---|---|
| Repeated PENDING, same immutable evidence | PASS | Returns existing record; no second write needed. |
| Reused version ID with changed source/artifact/provider/index evidence | PASS | Same identity key with different immutable evidence returns 409 conflict. |
| Duplicate ACTIVE version, one process | PASS | Publication checks active logical identity before state replacement. |
| ACTIVE -> DELETED / SUPERSEDED | PASS | Only stored ACTIVE may transition; timestamps are required by the record validator. |
| No provider publication reference or empty manifest | PASS | Cannot produce ACTIVE; returns sanitized `invalid_ledger_publication`. |
| Duplicate/malformed-but-syntactically-valid manifest entries | MAJOR | `ChunkManifestEntry` validates shape/hash only. `LedgerV2Record` accepts repeated `chunk_id` or `source_ref`; no uniqueness/conflict test exists. This undermines a future trusted chunk-membership invariant. |
| Manifest completeness / authoritative provider identity | MAJOR | The V2 model cannot establish that a non-empty manifest is complete or provider-authoritative. This is expected pending Quân/upstream, but V2 ACTIVE naming must not be interpreted as verified retrieval evidence. |
| Path traversal / unsafe storage path | MINOR | Ledger filename is fixed, but constructor accepts any `runtime_dir` path without repository-root containment validation. Current code has no external V2 route, so this is not an exposed production path; future wiring must supply a validated runtime directory. |
| Concurrent writers / lost update | MAJOR | Read-modify-write has no lock, compare-and-swap, generation number, or retry. Two processes can each pass the ACTIVE check and one replacement can lose the other's state. No cross-process safety is implemented or tested. |
| Failure between temporary write and replacement | MINOR | Replacement failure preserves old state in the tested case and cleanup is attempted. Crash/power-loss durability and recovery of leftover `.tmp` files are not tested/implemented. |

## 5. Independent test verification

Commands executed:

```text
lms-dlu-demo\venv\Scripts\python.exe -m py_compile deeptutor_integration\contracts.py deeptutor_integration\document_normalizer.py deeptutor_integration\moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py
lms-dlu-demo\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py tests\test_document_normalizer.py
```

- `py_compile` exit code: **0**.
- `pytest` exit code: **0**.
- Result: **20 passed, 3 subtests passed in 1.83s**.
- Environment failures: none.
- Round-13 count is reproduced exactly. These tests are local only; no Moodle, DB, provider, KB/index, LLM, or destructive operation ran.

## 6. Scope and compatibility assessment

V1 behavior is unchanged and direct `NormalizedDocument` construction stays compatible because `artifact_sha256` is optional. V2 is additive and separate from the V1 state file, which makes rollback straightforward: remove V2 types/tests before any future caller is introduced. The current production route remains unchanged.

The diff must not be described as secure retrieval, trusted provenance, cross-process-safe publication, or provider-attested ACTIVE state. It is local groundwork only.

## 7. Remaining blockers

### P0

1. Add manifest uniqueness/conflict validation (`chunk_id` and `source_ref`) and tests before treating V2 ACTIVE records as a basis for a verifier.
2. Define a process-safe publication strategy (file lock/CAS plus generation retry, or a transactional store) before any concurrent production writer uses V2.
3. Thọ-owned verified principal/course authorization must protect both query and grounded-chat routes.
4. Quân/upstream must provide raw pre-synthesis typed source export and authoritative publication/chunk evidence. PageIndex remains unsuitable before that contract exists.
5. Thiện must still integrate provider evidence, ACTIVE-only verifier, and no-LLM-on-unverified-context behavior after dependencies arrive.

### P1

1. Validate future V2 runtime storage against the configured repository root at composition time.
2. Specify and test recovery/cleanup for interrupted temporary files.
3. Run isolated HTTP and live-provider smoke tests only after secure route/provider wiring exists.

## 8. Commit readiness and corrections

**Verdict: FIX_REQUIRED.** Focused tests pass and V1 compatibility/production isolation are verified, but the two MAJOR issues above fail the task's `READY_TO_COMMIT` condition: a trusted chunk manifest needs internal uniqueness checks, and concurrent writers can lose updates.

Recommended minimal corrections before re-review:

1. Reject duplicate `chunk_id` and duplicate/conflicting `source_ref` in `LedgerV2Record`, with tests for both malformed cases.
2. Add an explicit documented single-process guard or implement and test process-safe locking/CAS. Do not claim cross-process safety until it exists.
3. Keep V2 detached from production ingestion/retrieval until Thọ/Quân contracts are implemented.
