# Final verified learning integration

Integration base: project-main `a3ae2e2c6d92b44692143c54a31383841b8bb0f8`.
Actual source histories are preserved: Thiện PR #35 `0edf2aa1eca53ef221751af4b6567e535963a272`,
Thọ `40623b9bd270223f98e24a8d72d67d69a23a8c51`, Quân `ef426c35e1a626421ca7a757c30bcccf0c6be012`.
No handoff report was used to reconstruct an implementation. The integration branch
is `integration/final-team-acceptance`; project-main is not merged or rewritten.

## One authority per decision

`MoodleTrustBoundary` is the personal identity, enrollment and exact capability
boundary. `CourseAuthorizationPolicy` remains the sole policy. The HTTP
`MoodleQueryAccess` only projects verified results and provides fresh reauthorization;
it no longer independently calls Moodle, constructs principals or grants writes.
Personal REST calls use POST form data and reject redirects. Personal tokens remain
request/Streamlit session memory, never principals, persisted contexts or logs.
Known configured operator/capability credentials are rejected before user verification.

`CanonicalCourseScope` binds Moodle namespace, numeric course ID, server-resolved
alias, logical KB and scope version. `AuthorizedCourseScope` retains its persisted
PR35 fields as a compatibility projection of that scope. The existing
`DeepTutorService.kb_name` is the only application Course → KB resolver; its output
is bound to the live numeric Moodle course. Duplicate aliases/KB mappings fail
closed. Student selectors and provider metadata cannot establish scope or identity.
Owner refs preserve the PR35 SHA-256(namespace + NUL + numeric Moodle user ID)
formula across the new prefixed Moodle principal issuer.

Lecturer writes require fresh `moodle/course:manageactivities` capability evidence
for the verified user and numeric course, including active enrollment. Configure
`MOODLE_CAPABILITY_SERVICE_TOKEN` for Moodle's
`core_enrol_get_enrolled_users_with_capability`; its credential is separate from
personal tokens. Missing/unavailable evidence yields 503, denied evidence 403,
before resource discovery/download. The former
`LMS_COURSE_ACTION_AUTHORIZER=module:function` hook is superseded by this actual
Thọ implementation. Student query access does not need the capability credential.

## Moodle lifecycle and publication

`MoodlePublicationAdapter` composes Thọ's actual guarded discovery, streaming
download, `SourceDocument`, complete scan and lifecycle signal functions with
Thiện's existing `VerifiedPublicationService`. It is not another Moodle client,
policy, KB resolver or RAG engine. Students see authorized ACTIVE publications;
only capability-authorized lecturers can discover unpublished Moodle resources.

Stable document identities include namespace/course/resource and, where necessary,
stable file IDs. Filename/version-hint changes do not change identity. Raw bytes
produce `content_hash`; Moodle's timestamp hint is stored separately. Internal
operator ingestion uses the same stable-ID helper and publication authority;
ambiguous multi-file operator requests fail instead of silently selecting a file.
Use the personal sync flow to select an exact multi-file identity.

Complete discovery/download, fresh reauthorization, stable snapshot confirmation
and all normalization precede destructive signals. CANDIDATE/UNCHANGED sources
publish before TOMBSTONE operations. A failed scan/normalization produces no
TOMBSTONE; a failed candidate keeps its previous ACTIVE version and stops deletion.
One OS scan lock serializes complete/per-document scans. One ledger lock atomically
activates each new manifest and supersedes the old source version. Successful
stable-ID publication also atomically retires its legacy numeric resource record.
Resource status and operator retirement resolve actual document IDs from resource
metadata. No implicit owner assignment, timer-based deletion or destructive schema
migration is introduced.

Publication uses the installed DeepTutor LlamaIndex raw-node bridge. Each immutable
source version gets a private physical KB; the logical course KB is server-owned.
The legacy node.text[:200] serializer never supplies verified grounding. Other
engine providers fail closed until equivalent full-node evidence is implemented.
Source IDs containing colons are hashed only for staging paths; provenance retains
the original stable ID. Existing containment/junction/symlink protections remain.

ACTIVE Ledger V2 records bind namespace/numeric course/logical KB/document/source
and artifact hashes, source version, real node IDs/content hashes and physical
publication/index identity. Retrieval verifies raw full nodes against that manifest.
Whole verified chunks are selected within 32,000 characters, without promoting a
preview to complete text. The ledger lease lasts through provider calls so retirement
cannot race an old prompt. Old private index files remain for recovery but are never
selected after supersession/deletion.

## Verified learning and storage

The application uses Quân's actual `LearningGenerationService`, Quiz/Flashcard
services and SQL repositories. Thiện's `VerifiedRetrievalContext` is projected to
Quân's strict `VerifiedLearningContext`; that DTO is not a trust authority.
The sole validator checks the in-process issuance receipt, exact context equality,
owner/course/logical KB, current Moodle authorization and current ACTIVE provenance.
Only literal True is accepted. Receipt lifetime equals the active context lease.
Unknown, changed or expired receipts fail closed. Quân revalidates before provider
use and again before persistence; revocation produces no trusted artifact.

QuizDefinitions.context_json and Flashcards.artifact_json are nullable additive
migrations. Quân stores full verified context, stable UUID question/artifact IDs,
server-only quiz keys and full card front/back with owner/course/context. Existing
VerifiedLearningArtifacts stores the canonical verification receipt and bindings;
new cards are not duplicated in its payload. No old rows are fabricated into verified
artifacts. Legacy NULL-context cards fail with controlled 409. Domain inserts use
explicit columns; schema initialization is repeatable on empty and populated DBs.

Public quiz DTOs exclude keys, explanations and raw context, including citation
previews before submission. Grading uses the stored definition and deterministic
GradingService with zero provider calls. Grading, answers, evidence and mastery are
one SQL transaction. Duplicate submits are controlled. Flashcard batches are atomic;
review IDs are idempotent with conflict detection. Owner/course guards protect all
artifact, attempt, review, history and progress routes. Both new /learning routes and
legacy factories receive the same verified scope dependency; imports stay internal.

Quiz review rechecks the saved canonical context against ACTIVE sources before any
optional explanation call. Retired context yields explanation unavailable and zero
LLM calls. Historical owner artifacts/grades remain readable. A historical citation
records verification at generation, not current ACTIVE status. Source integrity does
not certify factual correctness of model output.

A domain write followed by an application binding failure can leave an inaccessible
orphan. No binding means no student access through the production route guard;
operator recovery is required. This existing limit is retained rather than creating
another persistence architecture. Back up the real database before deployment.

Mastery and recommendations use server-owned evidence and deterministic rules.
No evidence is reported as unknown, not zero mastery. Optional prose cannot override
rule-selected actions. Chat reauthorizes before and after provider use and persists
only owner/course-bound history and stable source snapshots.

## Streamlit and operator routes

The active Streamlit app starts with personal-token login and /auth/me. Backend
scope, enrollment and capability decide course visibility and lecturer controls.
Logout clears session state. Documents, chat/history, public quiz/grade/review,
persisted flashcards/reviews and progress all use /learning routes. Lecturer controls
include exact per-document sync/retire and complete course sync. Students do not
perform privileged resource discovery. No UI role/student-ID claim establishes trust.
The old demo page remains unreachable after st.stop(). Detailed inventory, user/course
lists, material writes and internal learning imports require the operator credential;
anonymous health returns minimal signals only.

For a worktree, point DEEPTUTOR_DIR at the installed engine checkout. Configure SQL,
MOODLE_BASE_URL, personal-token web-service permissions, capability service evidence,
provider and embedding settings in an ignored local .env. Do not reuse MOODLE_TOKEN,
LMS_MOODLE_DISCOVERY_TOKEN or MOODLE_CAPABILITY_SERVICE_TOKEN for personal login.
Enable site_info, enrolled-course lookup and mod_resource discovery/file permissions
for intended personal tokens. File credentials use token, or explicitly configured
MOODLE_FILE_CREDENTIAL_PARAMETER=wstoken. Other parameter names fail closed.

## Reproducible acceptance and limits

Full regression:

```powershell
python -B -X utf8 -m pytest -q --tb=short -p no:cacheprovider tests
python -m pip check
git diff --check
```

The opt-in SQL test runs actual team API/repositories, migrations, transactions,
concurrency and rollback against two uniquely named temporary SQL Server databases.
Moodle/SDK/provider transports remain fake. It never migrates the production DB,
checks each database was absent before creation and drops only its own checked name.
It uses Windows integrated authentication; ODBC pooling is disabled for cleanup.

```powershell
$env:LMS_ACCEPTANCE_ENV_FILE = 'C:\path\to\ignored\.env'
python -B -X utf8 -m pytest -q -s --tb=short -p no:cacheprovider tests/manual/sql_final_team_acceptance.py
```

Streamlit AppTest verifies the real UI code with fake HTTP transport. It is not a
live browser result. The final acceptance report distinguishes all code, SQL and
live component statuses. Real personal student A/B and lecturer/capability credentials
were unavailable, so full live E2E remains NOT_VERIFIED. Local Ollama generation was
separately exercised through the actual provider implementation.

The OS publication lock lasts through generation; high concurrency can reach its
existing timeout. No load/performance claim is made. Old-index garbage collection,
legacy unreachable demo cleanup and FastAPI/Starlette deprecation migration remain
P2 follow-ups. No new dependencies, Gemini integration or extra RAG engine were added.
