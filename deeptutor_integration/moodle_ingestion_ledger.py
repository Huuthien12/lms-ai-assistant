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
        if not isinstance(data, dict):
            raise DeepTutorError("dedup_unavailable", "Document ingestion state is unavailable.", status_code=503)
        return data

    def contains(self, document: NormalizedDocument) -> bool:
        return self._records().get(self._key(document), {}).get("lifecycle") == "ACTIVE"

    def lifecycle(self, document: NormalizedDocument) -> str | None:
        return self._records().get(self._key(document), {}).get("lifecycle")

    def resource_lifecycle(self, course_id: str, document_id: str) -> str | None:
        matches = [value for value in self._records().values() if value.get("course_id") == course_id and value.get("document_id") == document_id]
        return max(matches, key=lambda value: value.get("indexed_at", "")).get("lifecycle") if matches else None

    def original_filename(self, course_id: str, document_id: str, sha256: str) -> str | None:
        record = self._records().get(f"{course_id}:{document_id}:{sha256}", {})
        value = record.get("original_filename")
        return value if isinstance(value, str) else None

    def record(self, document: NormalizedDocument) -> None:
        try:
            records = self._records()
            for value in records.values():
                if (
                    value.get("course_id") == document.course_id
                    and value.get("document_id") == document.document_id
                    and value.get("lifecycle") == "ACTIVE"
                ):
                    value["lifecycle"] = "SUPERSEDED"
            records[self._key(document)] = {
                "course_id": document.course_id,
                "document_id": document.document_id,
                "original_filename": document.original_filename,
                "sha256": document.sha256,
                "normalizer_version": document.normalizer_version,
                "lifecycle": "ACTIVE",
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

    def mark_deleted(self, course_id: str, document_id: str) -> bool:
        records = self._records()
        active = [
            value for value in records.values()
            if value.get("course_id") == course_id
            and value.get("document_id") == document_id
            and value.get("lifecycle") == "ACTIVE"
        ]
        if not active:
            return False
        latest = max(active, key=lambda value: value.get("indexed_at", ""))
        latest["lifecycle"] = "DELETED"
        try:
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(records, sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            raise DeepTutorError("dedup_unavailable", "Document ingestion state is unavailable.", status_code=503) from exc
        return True
