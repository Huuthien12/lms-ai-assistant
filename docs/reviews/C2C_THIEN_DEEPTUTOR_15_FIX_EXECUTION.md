# C2C THIEN-DEEPTUTOR-15 — Ledger V2 Manifest & Concurrency Corrections

## Workspace and scope

- Workspace: `D:\DeepTuTor`.
- Branch / HEAD: `thien/kb-retrieval-security` / `0b09fc9f810a71e425c25a550be621991b4af3ba`.
- Existing uncommitted Ledger V2 groundwork and review reports were preserved.
- This correction changed only `deeptutor_integration/moodle_ingestion_ledger.py`, `tests/test_moodle_ingestion_ledger_v2.py`, and this handoff report. Earlier artifact-hash changes in `contracts.py` and `document_normalizer.py` were not modified in this round.
- No production ingestion route, grounded chat, provider/CLI, authentication, database, Moodle, KB/index, or live service was changed or called.

## Fix A — manifest validation

`ChunkManifestEntry` now rejects blank `chunk_id` and `source_ref`. `LedgerV2Record` validates every manifest for:

- duplicate `chunk_id`;
- duplicate `source_ref`;
- a reused `source_ref` with a conflicting content SHA-256;
- blank logical identity/provider fields.

These checks are Pydantic model validation, so they apply equally to newly constructed records and persisted JSON loaded by `LedgerV2State`. Invalid evidence is rejected; it is never silently deduplicated. Active publication still separately requires a non-empty manifest and non-empty provider publication reference.

## Fix B — local cross-process mutation lock

`MoodleIngestionLedgerV2` now uses an OS advisory lock file (`moodle-ingestion-ledger-v2.lock`) around every read-modify-write mutation: pending creation, publication, failure, supersede, and delete. State is loaded only after the lock is acquired and persisted with the pre-existing temporary-file replacement.

- Lock acquisition is non-blocking/retried until a bounded timeout; timeout or OS failure raises sanitized `ledger_v2_lock_unavailable` (503).
- The lock file is not ledger evidence and is never parsed as state.
- The OS releases the held lock when a process exits; the empty/persistent lock file itself is harmless and does not imply ownership.
- This is local filesystem synchronization only, not a distributed lock or provider transaction.

## Tests

Commands:

```text
lms-dlu-demo\venv\Scripts\python.exe -m py_compile deeptutor_integration\moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py
lms-dlu-demo\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py tests\test_document_normalizer.py
```

Results:

- `py_compile` exit code: **0**.
- `pytest` exit code: **0**.
- **25 passed, 3 subtests passed in 4.23s**.

New focused coverage verifies duplicate chunk IDs, duplicate source references, conflicting source evidence, corrupt persisted manifest rejection, concurrent process PENDING writes retaining both records, competing process publication yielding exactly one ACTIVE version, and a held cross-process lock timing out fail-closed. Existing V1, original/artifact hash, and atomic replacement failure tests remain green.

## Security and compatibility result

- The two Round-14 MAJOR findings are resolved for this local V2 persistence implementation: manifests cannot contain duplicate/conflicting identity evidence, and tested local processes serialize mutations/reload the latest state under an OS lock.
- V1 behavior/file format and production routes remain unchanged; V2 remains isolated and inactive in production.
- Atomic replacement is retained. This implementation does not claim distributed transaction safety, provider publication atomicity, or filesystem durability through power loss.

## Remaining blockers

1. Quân/upstream must still provide raw pre-synthesis typed source export and authoritative provider publication/chunk evidence. This patch does not make a manifest authoritative by itself.
2. Thọ must still provide verified-principal/course authorization for both query and grounded-chat paths.
3. Thiện must later connect provider evidence, ACTIVE-only verifier, no-LLM-on-unverified-context behavior, and isolated route/live smoke tests.
4. Secure grounded retrieval remains blocked and was not enabled.

## Final status

**FIXED_PENDING_REVIEW.** Both scoped Round-14 findings are fixed and tested; planner review is still required before any commit decision.
