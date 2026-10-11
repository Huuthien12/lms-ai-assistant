# Verified learning integration decisions

Baseline: project-main a3ae2e2c6d92b44692143c54a31383841b8bb0f8 (merged #32, #33, #34).

## Identity and scope

The existing personal Moodle Bearer dependency now returns request-local callable
MoodleQueryAccess. Query callers retain their existing interface. Identity UI uses
/auth/me and only receives enrolled server-resolved scopes. Owner references hash
issuer plus subject; credentials remain request/session memory only. No shared
integration token is accepted as a user credential. Numeric Moodle IDs, aliases,
and logical KB IDs are kept separately in AuthorizedCourseScope.

CourseAuthorizationPolicy remains the only policy. Non-query sync decisions require
Tho's injected action authorizer; missing action evidence fails closed. Enrollment
alone does not authorize lecturer writes.

## Retrieval boundary under audit

The current DeepTutor LlamaIndex source serializer still uses node.text[:200].
Legacy CLI search cannot establish complete publication provenance. Integration
must use the existing engine's raw full-node interface and independently published
manifests, or fail closed; it must never promote the legacy snippet to verified text.
