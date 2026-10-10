# DeepTutor source provenance contract

## Observed flow

1. Moodle produces a `SourceDocument` with a Moodle course shortname, resource id, filename, and source bytes.
2. `DocumentNormalizer` produces a `NormalizedDocument`; its SHA-256 is calculated from the original source bytes.
3. The Moodle ingestion router builds the staged DeepTutor filename as `<document_id>-<sha256>.md`, maps the course to a KB, and passes selected metadata to `kb add`.
4. `MoodleIngestionLedger` records successful source versions under `course_id:document_id:sha256`, with lifecycle and original filename.
5. `CliDeepTutorAdapter.search(kb_id, question)` returns opaque JSON from `deeptutor kb search --format json`.

## Trust boundary

The ledger is the trusted local record for `course_id`, `document_id`, source SHA-256, lifecycle, and original filename. The current ledger does not record `kb_id`.

CLI search fields such as `title`, `chunk_id`, `content`, `source`, arbitrary `metadata`, `course_id`, and `kb_id` are untrusted for access-control purposes. In particular, the generated `<document_id>-<sha256>.md` title is an ingestion convention, not an adapter or upstream CLI response contract. It is currently suitable only for best-effort citation display.

## Required upstream contract before source ownership enforcement

Quân/DeepTutor must provide a versioned search-source schema for every result with either:

- immutable `document_id`, `source_sha256`, and `kb_id`; or
- one immutable ingestion identifier that is persisted by the ingestion ledger and returned by search.

The CLI must guarantee that these values originate from the indexed document metadata, not from generated text or caller input. The ledger must record the same KB binding (or a stable equivalent), and a verifier must accept only an `ACTIVE` ledger record whose course and KB match the authorized request. Missing, malformed, superseded, deleted, or mismatched provenance must fail closed.

Until that contract exists, course access is enforced before retrieval through the query authorizer. Returned sources must not be used to grant or extend authorization.
