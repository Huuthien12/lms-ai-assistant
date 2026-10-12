# Moodle trust and source lifecycle contract (Thọ → Thiện)

## Authority and transport

`deeptutor_integration.moodle_trust.MoodleTrustBoundary` is the personal-token
boundary. A caller extracts the original `Authorization: Bearer <personal Moodle
token>` with `personal_bearer_token`, then supplies that token to the boundary
for each operation. Never replace it with `MOODLE_TOKEN` or
`LMS_MOODLE_DISCOVERY_TOKEN`; those are integration and internal API credentials.
The boundary does not persist personal tokens or authorization decisions.

Moodle REST requests use `wstoken` against `webservice/rest/server.php`.
`core_webservice_get_site_info` binds that token to its Moodle `userid` and
site URL. `core_enrol_get_users_courses(userid=<verified user>)` supplies the
active, accessible enrollments; Moodle 4.5 uses active enrollments in this
function. A service account's course list is never used for the end user.

For lecturer sync, configure `MoodleCoreCapabilityEvidence(MoodleRest(base_url),
capability_service_token)`. It asks Moodle
`core_enrol_get_enrolled_users_with_capability` for the exact verified user,
numeric course, `moodle/course:manageactivities`, and `onlyactive=1`. The
Moodle administrator must grant this separate account enough rights for that
function, including the relevant course context. Missing function, denied
function, malformed response, or unavailable service fails with 503. A valid
response without the user denies sync with 403. Sync is the supported action
in the current adapter; Moodle resource creation, editing, and deletion are
not exposed by this integration.

## Canonical scope and public interface

Construct the boundary with a server-owned `kb_by_course_id` mapping keyed by
numeric Moodle IDs. Missing or duplicate KB mappings fail closed. Moodle
shortname is an alias resolved only within the verified user's live enrollment
response. Do not accept a client KB ID, role, Moodle user ID, or shortname as
proof of authority.

| Call | Result | Required consumer behavior |
| --- | --- | --- |
| `verify_credential(token)` | `(VerifiedPrincipal, MoodleUserBinding)` | Use `subject = Moodle userid`, `issuer = moodle:<site URL>` and matching namespace. Reverify each request; the 30-second principal expiry bounds an in-process decision and does not claim to be Moodle token expiry. |
| `authorize(token, selector, CourseAction.QUERY_COURSE)` | `AuthorizedMoodleCourse` | Use `scope.moodle_course_id` for authorization and `scope.kb_id` for retrieval. The returned decision is `LIVE`; no auth cache is used. |
| `authorize(token, selector, CourseAction.SYNC_COURSE_RESOURCE)` | Same | Require exact Moodle capability evidence. Use before any resource discovery. |
| `discover(token, selector)` | `(context, [MoodleResource])` | For lecturer sync only. Resource objects carry a validated, same-site file locator in memory; persist only non-URL fields. |
| `download(token, selector, document_id)` | `SourceDocument` | Reauthorizes before discovery and download. Sends file credential as `token` by default or explicit allowlisted `wstoken`; rejects redirects, query secrets, unexpected origin/path, oversized/empty/HTML payloads and invalid PDF bytes. |
| `scan_course(token, selector)` | `(context, [SourceDocument])` | Use for complete update/delete scans. It downloads all resources, reauthorizes and repeats discovery. Any failure or changed listing aborts the scan; an empty successful scan can generate tombstones. |
| `source_version(document)` + `lifecycle_signals(previous, current, moodle_namespace=..., course_id=...)` | `MoodleSourceVersion`, `MoodleLifecycleSignal` | Compare only snapshots from complete successful scans. `CANDIDATE` requests publication, `UNCHANGED` is idempotent, `TOMBSTONE` requests deletion. No signal marks a version active. |

`VerifiedPrincipal` and `MoodleUserBinding` reuse PR #34 contracts.
`CourseAuthorizationPolicy` remains the only course policy; the boundary
injects request-local verified identity, binding and Moodle evidence into it.
`CanonicalCourseScope` is the shared server-owned scope contract.

## Source identity and publication

`SourceDocument.course_id` is the enrolled shortname alias for existing
normalization consumers; `metadata.moodle_namespace` plus
`metadata.moodle_course_id` is the authoritative course identity.
`document_id` is a bounded stable key containing a digest of the Moodle site
namespace, numeric course ID, resource module ID, and (for a multi-file
resource) Moodle file ID. A multi-file response without stable file IDs fails
closed. This means renaming a single-file Moodle resource retains identity.
`content_hash`
is SHA-256 of raw bytes and is verified by `SourceDocument`; it is not the
Moodle `source_version_hint` (normally `timemodified`). The source metadata
also carries `moodle_resource_id`, `moodle_file_size` and `scope_version`.
It never carries a credential-bearing locator or fabricated chunk ID.

Thiện owns publication state. For source ID S, hash A remains active while a
new hash B is a `CANDIDATE`. Only a successful downstream publication may
activate B and supersede A. An identical hash emits `UNCHANGED` even if the
filename changes. A complete successful scan missing S emits `TOMBSTONE`;
Thiện must deactivate old retrieval artifacts after its deletion workflow
succeeds. A failed scan or ingestion leaves the previously published version
untouched. Retry the same snapshot deterministically.

## Integration and HTTP errors

Thiện's query route should call `authorize(..., QUERY_COURSE)` before
retrieval, construct the query from `scope.canonical_course_key` and
`scope.kb_id`, and reject an unrelated caller-supplied KB. Query and grounded
chat should reauthorize at the handoff points documented in
`C2C_THO_AUTH_26_PRODUCTION_INTEGRATION_CONTRACT.md`. Quân receives only the
verified canonical scope, never the token or raw enrollment.

`PrincipalRequiredError` is 401 (missing/invalid token),
`CourseAccessDeniedError` is 403 (not enrolled or capability denied), and
`MoodleAuthorizationUnavailableError` is 503 (Moodle, function, mapping, or
response unavailable/ambiguous). These are safe public errors and must not
be chained to raw request exceptions in HTTP responses or logs.

Existing `/moodle/*` demo endpoints still use the internal service key and
integration token. They are not personal-token routes. Production composition
and route wiring belong to the consuming route owners; until then, those
routes must not be treated as end-user authorization.
