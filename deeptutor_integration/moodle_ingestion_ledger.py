from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .contracts import NormalizedDocument
from .errors import DeepTutorError


class MoodleIngestionLedger:
    """Successful Moodle source versions, stored under the integration runtime."""

    def __init__(self, runtime_dir: Path) -> None:
        self.path = runtime_dir / "moodle-ingestion-index.json"

    @staticmethod
    def _key(document: NormalizedDocument) -> str:
        return f"{document.course_id}:{document.document_id}:{document.sha256}"

    def _records(self) -> dict[str, dict[str, str]]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeepTutorError("dedup_unavailable", "Document ingestion state is unavailable.", status_code=503) from exc
        return data if isinstance(data, dict) else {}

    def contains(self, document: NormalizedDocument) -> bool:
        return self._key(document) in self._records()

    def record(self, document: NormalizedDocument) -> None:
        try:
            records = self._records()
            records[self._key(document)] = {
                "course_id": document.course_id,
                "document_id": document.document_id,
                "original_filename": document.original_filename,
                "sha256": document.sha256,
                "normalizer_version": document.normalizer_version,
                "status": "indexed",
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(records, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
        except DeepTutorError:
            raise
        except OSError as exc:
            raise DeepTutorError("dedup_unavailable", "Document ingestion state is unavailable.", status_code=503) from exc
