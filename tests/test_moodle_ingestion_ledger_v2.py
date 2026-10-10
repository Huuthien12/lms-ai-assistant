from __future__ import annotations

from hashlib import sha256
import json
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from deeptutor_integration.contracts import SourceDocument
from deeptutor_integration.document_normalizer import DocumentNormalizer, artifact_sha256
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_ingestion_ledger import (
    ChunkManifestEntry,
    LedgerV2Lifecycle,
    LedgerV2Record,
    MoodleIngestionLedger,
    MoodleIngestionLedgerV2,
)


def pending(version: str = "version-0001") -> LedgerV2Record:
    return LedgerV2Record(
        source_namespace="moodle-dlu",
        course_id="INT1339",
        kb_id="int1339-python",
        document_id="resource-1",
        document_version_id=version,
        source_sha256="a" * 64,
        artifact_sha256="b" * 64,
        normalizer_version="markdown-v1",
        index_provider="llamaindex",
        index_version="chunker-v1",
        lifecycle=LedgerV2Lifecycle.PENDING,
        created_at="2026-10-10T00:00:00+00:00",
    )


def manifest() -> tuple[ChunkManifestEntry, ...]:
    return (ChunkManifestEntry(chunk_id="chunk-1", source_ref="provider-doc-1", content_sha256="c" * 64),)


def _create_pending_process(root: str, version: str, start, results) -> None:
    try:
        start.wait(10)
        MoodleIngestionLedgerV2(Path(root)).create_pending(pending(version))
        results.put(("created", version))
    except DeepTutorError as exc:
        results.put((exc.code, version))


def _publish_process(root: str, version: str, start, results) -> None:
    try:
        start.wait(10)
        MoodleIngestionLedgerV2(Path(root)).publish(pending(version), f"provider-{version}", manifest())
        results.put(("published", version))
    except DeepTutorError as exc:
        results.put((exc.code, version))


def _hold_lock_process(root: str, acquired, release) -> None:
    with MoodleIngestionLedgerV2(Path(root))._locked():
        acquired.set()
        release.wait(10)


def test_v2_schema_rejects_incomplete_active_and_unknown_fields():
    with pytest.raises(ValidationError, match="ACTIVE ledger records require"):
        LedgerV2Record(**{**pending().model_dump(), "lifecycle": "ACTIVE"})
    with pytest.raises(ValidationError):
        LedgerV2Record(**{**pending().model_dump(), "unexpected": "value"})


def test_manifest_rejects_duplicate_and_conflicting_identity_evidence():
    duplicate_chunk = (
        ChunkManifestEntry(chunk_id="chunk-1", source_ref="source-1", content_sha256="c" * 64),
        ChunkManifestEntry(chunk_id="chunk-1", source_ref="source-2", content_sha256="d" * 64),
    )
    with pytest.raises(ValidationError, match="duplicate chunk_id"):
        LedgerV2Record(**{**pending().model_dump(), "chunk_manifest": duplicate_chunk})

    duplicate_source = (
        ChunkManifestEntry(chunk_id="chunk-1", source_ref="source-1", content_sha256="c" * 64),
        ChunkManifestEntry(chunk_id="chunk-2", source_ref="source-1", content_sha256="c" * 64),
    )
    with pytest.raises(ValidationError, match="duplicate source_ref"):
        LedgerV2Record(**{**pending().model_dump(), "chunk_manifest": duplicate_source})

    conflicting_source = (
        ChunkManifestEntry(chunk_id="chunk-1", source_ref="source-1", content_sha256="c" * 64),
        ChunkManifestEntry(chunk_id="chunk-2", source_ref="source-1", content_sha256="d" * 64),
    )
    with pytest.raises(ValidationError, match="conflicting source_ref"):
        LedgerV2Record(**{**pending().model_dump(), "chunk_manifest": conflicting_source})


def test_normalized_artifact_hash_is_distinct_and_deterministic_for_unicode_and_newlines():
    source = SourceDocument(
        document_id="1", course_id="INT1339", filename="notes.md", mime_type="text/markdown",
        source="moodle", content="café\r\nline\rnext".encode("utf-8"),
    )
    normalized = DocumentNormalizer().normalize(source)
    assert normalized.markdown == "café\nline\nnext"
    assert normalized.sha256 == sha256(source.content).hexdigest()
    assert normalized.artifact_sha256 == artifact_sha256(normalized.markdown)
    assert normalized.artifact_sha256 != normalized.sha256
    assert artifact_sha256("café\nline\nnext") == artifact_sha256("café\nline\nnext")


def test_pending_is_idempotent_and_version_identity_is_immutable():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        first = ledger.create_pending(pending())
        assert ledger.create_pending(pending()) == first
        conflict = pending()
        conflict = LedgerV2Record(**{**conflict.model_dump(), "artifact_sha256": "d" * 64})
        with pytest.raises(DeepTutorError) as raised:
            ledger.create_pending(conflict)
        assert raised.value.code == "ledger_v2_conflict"


def test_pending_can_fail_but_cannot_publish_without_complete_manifest():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        record = ledger.create_pending(pending())
        with pytest.raises(DeepTutorError) as raised:
            ledger.publish(record, "provider-doc-1", ())
        assert raised.value.code == "invalid_ledger_publication"
        failed = ledger.mark_failed(record, "provider_unavailable")
        assert failed.lifecycle is LedgerV2Lifecycle.FAILED
        assert failed.failure_code == "provider_unavailable"
        with pytest.raises(DeepTutorError, match="Only a stored PENDING"):
            ledger.publish(record, "provider-doc-1", manifest())


def test_active_transitions_are_explicit_and_invalid_transitions_are_rejected():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        record = ledger.create_pending(pending())
        active = ledger.publish(record, "provider-doc-1", manifest())
        superseded = ledger.supersede(active)
        assert superseded.lifecycle is LedgerV2Lifecycle.SUPERSEDED
        with pytest.raises(DeepTutorError, match="Only a stored ACTIVE"):
            ledger.mark_deleted_v2(superseded)


def test_new_version_requires_explicit_supersede_before_becoming_active():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        first = ledger.publish(ledger.create_pending(pending()), "provider-doc-1", manifest())
        second = ledger.create_pending(pending("version-0002"))
        with pytest.raises(DeepTutorError, match="Supersede the active"):
            ledger.publish(second, "provider-doc-2", manifest())
        ledger.supersede(first)
        assert ledger.publish(second, "provider-doc-2", manifest()).lifecycle is LedgerV2Lifecycle.ACTIVE


def test_corrupt_v2_fails_closed_and_v1_records_are_not_imported():
    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "moodle-ingestion-index.json").write_text('{"legacy": {"lifecycle": "ACTIVE"}}', encoding="utf-8")
        assert MoodleIngestionLedgerV2(root)._state().records == {}
        (root / "moodle-ingestion-ledger-v2.json").write_text("[]", encoding="utf-8")
        with pytest.raises(DeepTutorError) as raised:
            MoodleIngestionLedgerV2(root)._state()
        assert raised.value.code == "ledger_v2_unavailable"


def test_corrupt_persisted_manifest_fails_closed():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        record = ledger.publish(ledger.create_pending(pending()), "provider-doc-1", manifest())
        state = ledger._state().model_dump(mode="json")
        key = ledger._key(record)
        state["records"][key]["chunk_manifest"].append(state["records"][key]["chunk_manifest"][0])
        ledger.path.write_text(json.dumps(state), encoding="utf-8")
        with pytest.raises(DeepTutorError) as raised:
            MoodleIngestionLedgerV2(Path(temporary))._state()
        assert raised.value.code == "ledger_v2_unavailable"


def test_atomic_write_failure_preserves_prior_state():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        first = ledger.create_pending(pending())
        with patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with pytest.raises(DeepTutorError) as raised:
                ledger.create_pending(pending("version-0002"))
        assert raised.value.code == "ledger_v2_unavailable"
        reloaded = MoodleIngestionLedgerV2(Path(temporary))._state()
        assert list(reloaded.records.values()) == [first]


def test_concurrent_pending_processes_preserve_both_records():
    with TemporaryDirectory() as temporary:
        context = get_context("spawn")
        start, results = context.Event(), context.Queue()
        processes = [
            context.Process(target=_create_pending_process, args=(temporary, version, start, results))
            for version in ("version-0001", "version-0002")
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert {results.get(timeout=1)[0] for _ in processes} == {"created"}
        assert len(MoodleIngestionLedgerV2(Path(temporary))._state().records) == 2


def test_competing_processes_cannot_publish_two_active_versions():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedgerV2(Path(temporary))
        ledger.create_pending(pending("version-0001"))
        ledger.create_pending(pending("version-0002"))
        context = get_context("spawn")
        start, results = context.Event(), context.Queue()
        processes = [
            context.Process(target=_publish_process, args=(temporary, version, start, results))
            for version in ("version-0001", "version-0002")
        ]
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        outcomes = [results.get(timeout=1)[0] for _ in processes]
        assert outcomes.count("published") == 1
        assert outcomes.count("invalid_ledger_transition") == 1
        records = MoodleIngestionLedgerV2(Path(temporary))._state().records.values()
        assert sum(record.lifecycle is LedgerV2Lifecycle.ACTIVE for record in records) == 1


def test_lock_timeout_fails_closed():
    with TemporaryDirectory() as temporary:
        context = get_context("spawn")
        acquired, release = context.Event(), context.Event()
        holder = context.Process(target=_hold_lock_process, args=(temporary, acquired, release))
        holder.start()
        try:
            assert acquired.wait(5)
            with pytest.raises(DeepTutorError) as raised:
                MoodleIngestionLedgerV2(Path(temporary), lock_timeout_seconds=0.05).create_pending(pending())
            assert raised.value.code == "ledger_v2_lock_unavailable"
        finally:
            release.set()
            holder.join(10)
        assert holder.exitcode == 0
