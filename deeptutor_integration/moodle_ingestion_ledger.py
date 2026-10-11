from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .contracts import NormalizedDocument
from .errors import DeepTutorError


class LedgerV2Lifecycle(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DELETED = "DELETED"
    FAILED = "FAILED"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


class ChunkManifestEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str = Field(min_length=1, max_length=500)
    source_ref: str = Field(min_length=1, max_length=1000)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("chunk_id", "source_ref")
    @classmethod
    def identity_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("chunk identity must not be blank")
        return value


class LedgerV2Record(BaseModel):
    """Immutable source/version evidence; V2 is not wired into production ingestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_schema_version: Literal["moodle-ledger/v2"] = "moodle-ledger/v2"
    source_namespace: str = Field(min_length=1, max_length=200)
    course_id: str = Field(min_length=1, max_length=120)
    kb_id: str = Field(min_length=1, max_length=120)
    document_id: str = Field(min_length=1, max_length=200)
    document_version_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{7,127}$")
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalizer_version: str = Field(min_length=1, max_length=120)
    index_provider: str = Field(min_length=1, max_length=120)
    index_version: str = Field(min_length=1, max_length=500)
    provider_publication_ref: str | None = Field(default=None, max_length=1000)
    chunk_manifest: tuple[ChunkManifestEntry, ...] = ()
    lifecycle: LedgerV2Lifecycle
    created_at: str = Field(min_length=1)
    published_at: str | None = None
    superseded_at: str | None = None
    deleted_at: str | None = None
    failed_at: str | None = None
    failure_code: str | None = Field(default=None, max_length=120)

    @field_validator(
        "source_namespace", "course_id", "kb_id", "document_id", "normalizer_version",
        "index_provider", "index_version", "created_at", "provider_publication_ref", "failure_code",
    )
    @classmethod
    def text_fields_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ledger identity fields must not be blank")
        return value

    @model_validator(mode="after")
    def validate_lifecycle_evidence(self) -> "LedgerV2Record":
        chunk_ids: set[str] = set()
        source_hashes: dict[str, str] = {}
        for chunk in self.chunk_manifest:
            if chunk.chunk_id in chunk_ids:
                raise ValueError("chunk manifest contains duplicate chunk_id")
            chunk_ids.add(chunk.chunk_id)
            previous_hash = source_hashes.get(chunk.source_ref)
            if previous_hash is not None:
                if previous_hash != chunk.content_sha256:
                    raise ValueError("chunk manifest contains conflicting source_ref evidence")
                raise ValueError("chunk manifest contains duplicate source_ref")
            source_hashes[chunk.source_ref] = chunk.content_sha256
        if self.lifecycle is LedgerV2Lifecycle.ACTIVE:
            if not self.provider_publication_ref or not self.chunk_manifest or not self.published_at:
                raise ValueError("ACTIVE ledger records require publication reference, manifest, and published_at")
        if self.lifecycle is LedgerV2Lifecycle.FAILED and (not self.failed_at or not self.failure_code):
            raise ValueError("FAILED ledger records require failed_at and failure_code")
        if self.lifecycle is LedgerV2Lifecycle.SUPERSEDED and not self.superseded_at:
            raise ValueError("SUPERSEDED ledger records require superseded_at")
        if self.lifecycle is LedgerV2Lifecycle.DELETED and not self.deleted_at:
            raise ValueError("DELETED ledger records require deleted_at")
        return self

    def identity(self) -> tuple[str, str, str, str, str]:
        return (
            self.source_namespace,
            self.course_id,
            self.kb_id,
            self.document_id,
            self.document_version_id,
        )

    def immutable_evidence(self) -> tuple[str, ...]:
        return (
            self.source_sha256,
            self.artifact_sha256,
            self.normalizer_version,
            self.index_provider,
            self.index_version,
        )

    def logical_identity(self) -> tuple[str, str, str, str]:
        return self.source_namespace, self.course_id, self.kb_id, self.document_id


class LedgerV2State(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    ledger_schema_version: Literal["moodle-ledger/v2"] = "moodle-ledger/v2"
    records: dict[str, LedgerV2Record] = Field(default_factory=dict)


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


class MoodleIngestionLedgerV2:
    """Isolated immutable ledger groundwork; it deliberately has no production callers."""

    def __init__(self, runtime_dir: Path, *, lock_timeout_seconds: float = 5.0) -> None:
        self.path = runtime_dir / "moodle-ingestion-ledger-v2.json"
        self.lock_path = runtime_dir / "moodle-ingestion-ledger-v2.lock"
        self.lock_timeout_seconds = lock_timeout_seconds

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _key(record: LedgerV2Record) -> str:
        raw = "\0".join(record.identity()).encode("utf-8")
        return sha256(raw).hexdigest()

    def _state(self) -> LedgerV2State:
        if not self.path.exists():
            return LedgerV2State()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            state = LedgerV2State.model_validate(data)
            for key, record in state.records.items():
                if key != self._key(record):
                    raise ValueError("record key does not match immutable identity")
            return state
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise DeepTutorError("ledger_v2_unavailable", "Ledger V2 state is unavailable.", status_code=503) from exc

    def _write(self, state: LedgerV2State) -> None:
        temporary = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(state.model_dump(mode="json"), sort_keys=True), encoding="utf-8")
            temporary.replace(self.path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise DeepTutorError("ledger_v2_unavailable", "Unable to persist Ledger V2 state.", status_code=503) from exc

    @staticmethod
    def _try_lock(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock(handle) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            return
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.lock_timeout_seconds < 0:
            raise DeepTutorError("ledger_v2_lock_unavailable", "Ledger V2 lock is unavailable.", status_code=503)
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            with self.lock_path.open("a+b") as handle:
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                deadline = time.monotonic() + self.lock_timeout_seconds
                while True:
                    try:
                        self._try_lock(handle)
                        break
                    except OSError as exc:
                        if time.monotonic() >= deadline:
                            raise DeepTutorError(
                                "ledger_v2_lock_unavailable", "Ledger V2 lock is unavailable.", status_code=503
                            ) from exc
                        time.sleep(0.01)
                try:
                    yield
                finally:
                    self._unlock(handle)
        except DeepTutorError:
            raise
        except OSError as exc:
            raise DeepTutorError("ledger_v2_lock_unavailable", "Ledger V2 lock is unavailable.", status_code=503) from exc

    @staticmethod
    def _replacement(record: LedgerV2Record, **changes: object) -> LedgerV2Record:
        return LedgerV2Record.model_validate({**record.model_dump(mode="json"), **changes})

    def create_pending(self, record: LedgerV2Record) -> LedgerV2Record:
        if record.lifecycle is not LedgerV2Lifecycle.PENDING:
            raise DeepTutorError("invalid_ledger_transition", "Only PENDING records can be created.", status_code=422)
        with self._locked():
            state = self._state()
            key = self._key(record)
            existing = state.records.get(key)
            if existing is not None:
                if existing.immutable_evidence() == record.immutable_evidence():
                    return existing
                raise DeepTutorError("ledger_v2_conflict", "Document version identity conflicts with existing evidence.", status_code=409)
            records = dict(state.records)
            records[key] = record
            self._write(LedgerV2State(records=records))
            return record

    def publish(
        self,
        record: LedgerV2Record,
        provider_publication_ref: str,
        chunk_manifest: tuple[ChunkManifestEntry, ...],
    ) -> LedgerV2Record:
        with self._locked():
            state = self._state()
            key = self._key(record)
            existing = state.records.get(key)
            if existing is None or existing.lifecycle is not LedgerV2Lifecycle.PENDING:
                raise DeepTutorError("invalid_ledger_transition", "Only a stored PENDING record can be published.", status_code=409)
            if existing.immutable_evidence() != record.immutable_evidence():
                raise DeepTutorError("ledger_v2_conflict", "Document version evidence changed before publication.", status_code=409)
            if any(
                candidate.lifecycle is LedgerV2Lifecycle.ACTIVE
                and candidate.logical_identity() == existing.logical_identity()
                and candidate.document_version_id != existing.document_version_id
                for candidate in state.records.values()
            ):
                raise DeepTutorError("invalid_ledger_transition", "Supersede the active document version before publication.", status_code=409)
            try:
                published = self._replacement(
                    existing,
                    lifecycle=LedgerV2Lifecycle.ACTIVE,
                    provider_publication_ref=provider_publication_ref,
                    chunk_manifest=chunk_manifest,
                    published_at=self._now(),
                )
            except ValidationError as exc:
                raise DeepTutorError("invalid_ledger_publication", "Ledger V2 publication evidence is incomplete.", status_code=422) from exc
            records = dict(state.records)
            records[key] = published
            self._write(LedgerV2State(records=records))
            return published

    def mark_failed(self, record: LedgerV2Record, failure_code: str) -> LedgerV2Record:
        with self._locked():
            state = self._state()
            key = self._key(record)
            existing = state.records.get(key)
            if existing is None or existing.lifecycle is not LedgerV2Lifecycle.PENDING:
                raise DeepTutorError("invalid_ledger_transition", "Only a stored PENDING record can fail.", status_code=409)
            failed = self._replacement(
                existing,
                lifecycle=LedgerV2Lifecycle.FAILED,
                failed_at=self._now(),
                failure_code=failure_code,
            )
            records = dict(state.records)
            records[key] = failed
            self._write(LedgerV2State(records=records))
            return failed

    def supersede(self, record: LedgerV2Record) -> LedgerV2Record:
        return self._transition_active(record, LedgerV2Lifecycle.SUPERSEDED)

    def mark_deleted_v2(self, record: LedgerV2Record) -> LedgerV2Record:
        return self._transition_active(record, LedgerV2Lifecycle.DELETED)

    def _transition_active(self, record: LedgerV2Record, target: LedgerV2Lifecycle) -> LedgerV2Record:
        with self._locked():
            state = self._state()
            key = self._key(record)
            existing = state.records.get(key)
            if existing is None or existing.lifecycle is not LedgerV2Lifecycle.ACTIVE:
                raise DeepTutorError("invalid_ledger_transition", "Only a stored ACTIVE record can transition.", status_code=409)
            timestamp_key = "superseded_at" if target is LedgerV2Lifecycle.SUPERSEDED else "deleted_at"
            transitioned = self._replacement(existing, lifecycle=target, **{timestamp_key: self._now()})
            records = dict(state.records)
            records[key] = transitioned
            self._write(LedgerV2State(records=records))
            return transitioned
