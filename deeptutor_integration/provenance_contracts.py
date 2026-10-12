from __future__ import annotations

import json
import re
import unicodedata
from hashlib import sha256
from typing import Final

from .document_normalizer import artifact_sha256, source_sha256
from .errors import DeepTutorError


SOURCE_REF_PREFIX: Final = "ssv1:"
DOCUMENT_VERSION_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,127}$")


def _invalid(message: str) -> DeepTutorError:
    return DeepTutorError("invalid_provenance_identifier", message, status_code=422)


def _canonical_identifier(value: str, *, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid(f"{name} is invalid.")
    if len(value) > maximum or value != value.strip() or not unicodedata.is_normalized("NFC", value):
        raise _invalid(f"{name} is invalid.")
    if any(ord(character) <= 0x1F or 0x7F <= ord(character) <= 0x9F for character in value):
        raise _invalid(f"{name} is invalid.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _invalid(f"{name} is invalid.") from exc
    return value


def validate_document_version_id(value: str) -> str:
    value = _canonical_identifier(value, name="document_version_id", maximum=128)
    if not DOCUMENT_VERSION_ID_PATTERN.fullmatch(value):
        raise _invalid("document_version_id is invalid.")
    return value


def canonical_source_ref(kb_id: str, document_version_id: str, chunk_id: str) -> str:
    values = (
        _canonical_identifier(kb_id, name="kb_id", maximum=120),
        validate_document_version_id(document_version_id),
        _canonical_identifier(chunk_id, name="chunk_id", maximum=500),
    )
    try:
        encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        encoded.encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise _invalid("source_ref is invalid.") from exc
    reference = f"{SOURCE_REF_PREFIX}{encoded}"
    if len(reference) > 1000:
        raise _invalid("source_ref is invalid.")
    return reference


def parse_canonical_source_ref(value: str) -> tuple[str, str, str]:
    if not isinstance(value, str) or not value.startswith(SOURCE_REF_PREFIX):
        raise DeepTutorError("invalid_source_ref", "Source reference is invalid.", status_code=422)
    encoded = value[len(SOURCE_REF_PREFIX):]
    try:
        parsed = json.loads(encoded)
    except (TypeError, json.JSONDecodeError) as exc:
        raise DeepTutorError("invalid_source_ref", "Source reference is invalid.", status_code=422) from exc
    if not isinstance(parsed, list) or len(parsed) != 3 or not all(isinstance(item, str) for item in parsed):
        raise DeepTutorError("invalid_source_ref", "Source reference is invalid.", status_code=422)
    try:
        canonical = canonical_source_ref(parsed[0], parsed[1], parsed[2])
    except DeepTutorError as exc:
        raise DeepTutorError("invalid_source_ref", "Source reference is invalid.", status_code=422) from exc
    if value != canonical:
        raise DeepTutorError("invalid_source_ref", "Source reference is invalid.", status_code=422)
    return parsed[0], parsed[1], parsed[2]


def original_source_sha256(content: bytes) -> str:
    """SHA-256 of original Moodle resource bytes; delegates to the normalizer contract."""
    return source_sha256(content)


def normalized_artifact_sha256(markdown: str) -> str:
    """SHA-256 of exact already-normalized Markdown UTF-8 bytes."""
    return artifact_sha256(markdown)


def canonical_chunk_sha256(content: str) -> str:
    """SHA-256 of complete raw chunk UTF-8 text without normalization or truncation."""
    if not isinstance(content, str) or not content:
        raise DeepTutorError("invalid_chunk_content", "Chunk content is invalid.", status_code=422)
    try:
        return sha256(content.encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        raise DeepTutorError("invalid_chunk_content", "Chunk content is invalid.", status_code=422) from exc
