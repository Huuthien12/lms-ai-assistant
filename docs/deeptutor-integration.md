# DeepTutor integration boundary

This module is owned by **Lương Hữu Thiện (DeepTutor)**. It isolates DeepTutor v1.5.16 runtime, knowledge-base, document-ingestion, retrieval, health, and error-normalization behavior from LMS/Moodle and AI-personalization code.

## Stable HTTP contract

- `POST /deeptutor/documents` — ingest one supported document into a course knowledge base.
- `POST /deeptutor/knowledge-bases` — create a course knowledge base from its first document.
- `POST /deeptutor/query` — run neutral retrieval/query against a ready knowledge base.
- `GET /deeptutor/health` — check local DeepTutor runtime availability without invoking it.
- `GET /deeptutor/status` — list knowledge bases or inspect one with `?kb_id=...`.

Responses use a stable envelope with `success`, `data`, and `error`. Failures have a stable `code` and safe `message`; command tracebacks and secrets are not exposed.

## Runtime adapter

`deeptutor_integration/` invokes only the public DeepTutor CLI (`kb list`, `kb info`, `kb create`, `kb add`, and `kb search`). Defaults are repository-relative and may be overridden with `DEEPTUTOR_DIR`, `DEEPTUTOR_EXE`, `DEEPTUTOR_RUNTIME_DIR`, and `DEEPTUTOR_TIMEOUT_SECONDS`.

Generated document copies are written below `.deeptutor-runtime/`, which is excluded from Git. The upstream `DeepTutor/` submodule is not modified.

## Ownership boundary

The module accepts neutral identifiers, document metadata, and questions. It does not depend on Moodle objects, the LMS SQL schema, Streamlit, prompt personalization, model selection, or recommendation logic. LMS callers translate their own objects into these DTOs; the AI owner may consume retrieval results without placing provider policy inside this module.

Real indexing and query execution require an installed DeepTutor runtime and its external model/API configuration. Unit tests use a fake adapter and do not claim live LLM coverage.
