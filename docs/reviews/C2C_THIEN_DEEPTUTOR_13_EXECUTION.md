# C2C THIEN-DEEPTUTOR-13 — Ledger V2 Groundwork Execution

## Workspace

- Workspace: `D:\DeepTuTor`.
- Branch / HEAD: `thien/kb-retrieval-security` / `0b09fc9f810a71e425c25a550be621991b4af3ba`.
- The worktree already contained untracked review reports; they were preserved. No branch switch, commit, push, merge, rebase, deployment, live Moodle call, DB operation, KB/index operation, or deletion was performed.

## Files changed

- `deeptutor_integration/contracts.py`
- `deeptutor_integration/document_normalizer.py`
- `deeptutor_integration/moodle_ingestion_ledger.py`
- `tests/test_moodle_ingestion_ledger_v2.py`
- This handoff report.

## Implementation

1. `NormalizedDocument` now has additive optional `artifact_sha256`; existing V1 fixtures remain valid when it is absent.
2. `DocumentNormalizer.normalize()` computes `artifact_sha256` from the exact UTF-8 Markdown after newline normalization. `sha256` remains the original source-byte hash.
3. `MoodleIngestionLedgerV2` is an isolated local persistence path in `moodle_ingestion_ledger.py`, using a separate `moodle-ingestion-ledger-v2.json` file. The production V1 `MoodleIngestionLedger` and production ingestion router remain unchanged.
4. V2 records are strict immutable Pydantic models with schema version, namespace, canonical course/KB, document/version identity, source/artifact hashes, normalizer/provider/index identity, lifecycle timestamps, provider publication reference, and chunk manifest.
5. V2 supports idempotent PENDING creation; PENDING -> FAILED; PENDING -> ACTIVE only after a non-empty chunk manifest, provider publication reference, and publication time validate; ACTIVE -> SUPERSEDED/DELETED only through explicit transitions.
6. At most one ACTIVE record can exist for one `(source_namespace, course_id, kb_id, document_id)`; a replacement must explicitly supersede the active version before publishing a new one.

## Security invariants verified

- V2 does not read, rewrite, or promote V1 records. A V1 ledger file is ignored by V2, so it cannot become verified evidence.
- V2 rejects malformed state, mismatched on-disk identity keys, incomplete ACTIVE publication, invalid transitions, and immutable-version evidence conflicts.
- Atomic local persistence writes a temporary file then replaces the V2 file. If replacement fails, the old persisted state remains readable; cross-process transaction safety is **not claimed**.
- No filename, caller KB, retrieval order, or provider output is used to derive a document version or chunk identity.
- V2 is not wired into retrieval, so it does not claim provider provenance verification or secure grounded retrieval.

## Tests executed

Command:

```text
lms-dlu-demo\venv\Scripts\python.exe -m py_compile deeptutor_integration\contracts.py deeptutor_integration\document_normalizer.py deeptutor_integration\moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py
lms-dlu-demo\venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests\test_moodle_ingestion_ledger.py tests\test_moodle_ingestion_ledger_v2.py tests\test_document_normalizer.py
```

Result: **20 passed, 3 subtests passed**. Coverage includes V2 schema validation, separate original/artifact hashes with Unicode/newline normalization, idempotent PENDING, immutable version conflict, PENDING -> FAILED, incomplete publication rejection, lifecycle guards, corrupt state fail-closed, V1 non-import, atomic replacement failure, and V1/normalizer regression.

No live integration suite was run because this patch intentionally has no production wiring and the task forbids live services.

## Compatibility and rollback

- Existing V1 file name, methods, lifecycle behavior, and router caller remain unchanged.
- The optional artifact field preserves existing manually constructed `NormalizedDocument` fixtures.
- Rollback is limited to removing unused V2 types/persistence and its tests; V1 data is untouched. No automatic migration was added.

## Remaining P0 blockers

1. **Thọ:** backend-verified principal, trusted Moodle binding, and course authorization must be composed for both `/deeptutor/query` and `/chat/grounded` before retrieval.
2. **Quân/upstream:** raw pre-synthesis, typed `SearchSourceV1` export with stable document version/chunk evidence is required; PageIndex remains unsuitable because it reasons before an application verifier can filter sources.
3. **Thiện, after dependencies exist:** provider publication must produce trusted chunk manifests; a verifier must enforce ACTIVE-only evidence before reranking or LLM calls; route integration then needs isolated HTTP and live smoke tests.

## Final status

**EXECUTED.** Ledger V2 groundwork is implemented and tested in isolation. Secure grounded retrieval remains **BLOCKED** and no production behavior has changed.
