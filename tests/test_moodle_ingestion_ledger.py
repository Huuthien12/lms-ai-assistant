from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from deeptutor_integration.contracts import NormalizedDocument
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedger


def document(sha256: str) -> NormalizedDocument:
    return NormalizedDocument(
        document_id="1", course_id="INT1339", original_filename="lecture.pdf",
        original_mime_type="application/pdf", source="moodle", sha256=sha256,
        markdown="# lecture", normalizer_version="markdown-v1",
    )


def test_lifecycle_active_superseded_deleted_and_persists():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedger(Path(temporary))
        first, second = document("a" * 64), document("b" * 64)
        ledger.record(first)
        assert ledger.contains(first)
        assert ledger.lifecycle(first) == "ACTIVE"
        ledger.record(second)
        assert ledger.lifecycle(first) == "SUPERSEDED"
        assert ledger.lifecycle(second) == "ACTIVE"
        assert MoodleIngestionLedger(Path(temporary)).lifecycle(second) == "ACTIVE"
        assert ledger.mark_deleted("INT1339", "1")
        assert ledger.lifecycle(second) == "DELETED"
        assert not ledger.contains(second)


def test_unrecorded_changed_version_leaves_active_version_unchanged():
    with TemporaryDirectory() as temporary:
        ledger = MoodleIngestionLedger(Path(temporary))
        active, failed = document("a" * 64), document("b" * 64)
        ledger.record(active)
        # A failed ingestion never calls record(), so its candidate hash has no lifecycle state.
        assert ledger.lifecycle(active) == "ACTIVE"
        assert ledger.lifecycle(failed) is None


def test_corrupted_ledger_fails_safely():
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "moodle-ingestion-index.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(DeepTutorError) as raised:
            MoodleIngestionLedger(Path(temporary)).contains(document("a" * 64))
        assert raised.value.code == "dedup_unavailable"
