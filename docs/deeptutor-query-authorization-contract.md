# Runtime query/chat authorization

Production injects `create_moodle_query_authorizer` into `/deeptutor/query` and
one shared handler registered as `/chat/grounded` and `/lms/chat`. The LMS chat
HTTP self-proxy is retired: authorization and retrieval run once per request.

## Credentials and configuration

Set `MOODLE_BASE_URL` to the configured Moodle instance. Each API caller supplies
`Authorization: Bearer <personal Moodle web-service token>`. Moodle must enable
`core_webservice_get_site_info` and `core_enrol_get_users_courses` for that token's
service. The backend verifies credentials live and looks up active, accessible
enrollments for the verified Moodle user ID. Tokens are sent in POST form data;
authorization requests do not follow redirects. `MOODLE_TOKEN` and
`LMS_MOODLE_DISCOVERY_TOKEN` remain ingestion/discovery credentials and grant no
student query rights. Caller roles, student IDs and principal headers grant none.

The existing Streamlit demo-password login does not supply a personal Moodle
token. Its chat now fails closed until the separate verified-login flow forwards
that credential. Do not replace it with a shared service token or disable guards.

## Canonical scope and policy

The authoritative enrollment record supplies numeric Moodle course ID and
shortname. The shortname is resolved by `DeepTutorService.kb_name`; explicit KBs
must match. Ambiguous mappings fail closed. `CourseAuthorizationPolicy` from
PR #34 validates the principal, Moodle binding, exact course/action and LIVE
allow decision. Only then does the checker replace the query course/KB with the
server-resolved values and permit `service.query`, `adapter.search` and the LLM.
No authorization decisions or credentials are cached across requests.

Missing/invalid credentials return 401; a verified user without course enrollment
returns 403; missing configuration, unavailable auth dependencies or malformed
authoritative responses return sanitized 503. Explicit KB mismatch remains 422.
Retrieval error envelopes return 502; `needs_reindex` returns 409. A successful
empty retrieval still yields the existing safe no-context response without LLM.

## Remaining boundaries

Full chunk provenance and ACTIVE document-version verification remain follow-ups;
CLI metadata is not ownership evidence. `GET /deeptutor/status`, learning/history
APIs and ingestion/write course authorization are outside this query/chat fix.
The status inventory still requires an operational/admin boundary.

Tests use the actual runtime adapter/policy with mocked Moodle transport and
HTTP routes. They are not live Moodle, RAG, SQL or LLM E2E evidence.
