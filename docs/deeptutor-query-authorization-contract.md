# DeepTutor query authorization contract

`POST /deeptutor/query` is fail-closed unless application composition injects a query-authorizer dependency into `create_router`. That dependency must establish a verified principal and return a callable which receives the parsed `QueryInput`. The callable must reject the actual `QueryInput.course_id` unless the principal has authoritative access to that course, before `DeepTutorService.query` runs. A valid service token by itself is not course authorization.

`DeepTutorService.kb_name` deterministically maps a canonical course identifier to one knowledge-base identifier. An explicit `kb_id` must equal that mapping; it is not a caller-controlled selector. Course identifiers must use lowercase/uppercase ASCII letters, digits, `_`, or `-` (normalised to lowercase), so distinct raw values cannot collapse onto one fallback KB name.

The CLI adapter's `search(kb_id, question)` response is opaque. Any source metadata it returns, including `course_id` or `kb_id`, is not proof of ownership and must not be used to grant access or to filter authorization decisions.

Required integration contracts:

- Thọ/application composition: a FastAPI query dependency backed by verified identity, role, and authoritative course enrollment/access data. It must deny before retrieval and retain lecturer/admin boundaries.
- Quân/DeepTutor adapter: if future source-level isolation is required, provide trusted, stable document and KB provenance tied to the immutable ingestion ledger. The current CLI search contract does not provide that guarantee.
- LMS grounded-chat callers that invoke `DeepTutorService.query` directly must enforce the same verified course authorization at their own route boundary; the `/deeptutor/query` dependency cannot protect those calls.

`GET /deeptutor/status` currently preserves its existing response contract and can expose every KB when called without `kb_id`. Minimum policy: application composition should protect the list form with a verified principal and restrict it to an operational/admin role; course-scoped callers should use a course-authorized status path rather than treating this list as an enrollment API. This phase does not alter that endpoint.
