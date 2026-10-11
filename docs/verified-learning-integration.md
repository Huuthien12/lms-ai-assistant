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

## Legacy API authorization

Production installs a route guard around the existing domain routers. Query/chat
retain their own shared dependency. History and progress bind owner_ref before
operation; attempt/quiz/card operations look up persisted owner and course before
mutation. Unbound legacy learning artifacts are not promoted to owned artifacts.
Detailed inventory, global user/course listings, material writes and internal
learning registration require the existing operator service credential. Public
health stays minimal. New /learning routes apply the same dependency directly.

The old SQL schemas are preserved. VerifiedLearningArtifacts is an additive binding
and context table, not a destructive migration or implicit owner backfill.

## Full-source publication and lifecycle

The adapter uses DeepTutor's existing LlamaIndex persisted nodes and plain vector
retriever, avoiding the legacy 200-character serializer and query-fusion/synthesis.
Every document version is indexed into an immutable private engine KB. The logical
course KB remains server-controlled; private publication KBs are never selectors
accepted from a student. Other engine providers fail closed until their raw-node
adapter supports equivalent evidence.

Canonical source-ref/hash helpers were adopted from the audited local groundwork;
the synthetic-only verifier was not promoted into production evidence. The single
AuthorizedCourseScope now lives in integration contracts. ACTIVE Ledger V2 records
bind namespace, numeric course, logical KB, source/artifact hashes, real engine node
IDs/content hashes and publication/index identity. No filename-derived ownership.

Ingestion publishes a manifest only after full-node export succeeds. A single
locked write retires the old record and activates the new one. Failed publication
marks FAILED and leaves the previous ACTIVE record intact. Update/delete serializes
with context leases held through provider calls, so completed retirement cannot
race an old source into a prompt. Private old index artifacts are retained for
recovery but never selected by ACTIVE-only retrieval.

The context builder selects whole verified chunks within 32,000 characters. UI
preview is separate; citations correspond exactly to selected prompt chunks.
Resource-derived paths reject traversal/absolute forms and resolved-root escapes.
