# P8 demo and deployment procedure

This procedure is for an operator-controlled Windows demonstration or deployment review. It does not authorize changing a production database, Moodle site, Docker volume, or network exposure.

## Prerequisites and local configuration

- Install the LMS Python environment from `lms-dlu-demo/requirements-dev.txt`, SQL Server tooling, Docker Desktop, and either Ollama or a locally supplied Groq API key.
- Configure `MOODLE_BASE_URL`, SQL Server connection settings, DeepTutor settings, and provider settings in the operator's ignored environment file or Windows user environment. Never commit `.env`, Moodle tokens, provider keys, DPAPI blobs, logs, database files, or runtime directories.
- The launcher intentionally sets `DEMO_QUICK_LOGIN_ENABLED=true`. Each Windows user must run `lms-dlu-demo\provision_demo_accounts.ps1` and enter their own Moodle personal tokens. That script stores per-user DPAPI blobs under `%LOCALAPPDATA%\DeepTutor\demo-accounts`; none are distributed in Git.
- Quick login reads only a named DPAPI blob, fails closed if it is missing or unreadable, and verifies every selected token through `/auth/me`. It does not bypass Moodle identity or course authorization.

## Pre-deployment checks

1. Back up the existing approved LMS SQL Server database and record its schema/version before any deployment action.
2. Confirm Moodle is reachable, required users are enrolled, and intended personal tokens have the required course and file capabilities.
3. Confirm Docker containers `deeptutor-moodle` and `deeptutor-moodle-db` are already running; do not use destructive Docker commands.
4. Confirm the selected provider is reachable. For Groq, provide `GROQ_API_KEY` only in the operator shell/environment. For Ollama, ensure the configured model and embedding model are available.
5. Review `docs/verified-learning-integration.md` before applying the application's repeatable additive schema initialization. Existing Quiz, Flashcard, ReviewBatch, LearningEvent, TopicMastery, and artifact-binding data must remain intact. If the schema check fails, stop and restore/forward-recover from the backup; do not drop or recreate the database.

## Safe startup and smoke check

1. Run `lms-dlu-demo\start_lms.bat groq` or `lms-dlu-demo\start_lms.bat ollama` from Windows.
2. The launcher checks Moodle, the approved local SQL target, provider readiness, and occupied ports. It refuses to replace an existing process.
3. Confirm FastAPI at `http://127.0.0.1:8001/openapi.json` and Streamlit at `http://127.0.0.1:8502/_stcore/health`. Both services deliberately bind only to `127.0.0.1`.
4. If startup fails, use the named FastAPI/Streamlit window for the actual error. Do not expose either service on a network interface as a workaround.

## Demonstration sequence

1. Sign in with a personal Moodle token or a locally provisioned demo account; show `/auth/me` identity and allowed courses.
2. Select an authorized course and an ACTIVE document. Show that a foreign or retired document is unavailable.
3. Ask a Tutor question and show its grounded citations.
4. Generate an evidence-grounded Quiz, submit at least one incorrect answer, and show deterministic grade plus grounded explanation.
5. Select **Ôn tập câu sai bằng Flashcard**. Show a READY review batch and rate cards with AGAIN, HARD, GOOD, and EASY.
6. Open Progress to show persisted evidence, mastery/confidence, and the explainable recommendation. Use the existing Quiz or Flashcards tabs to act on it.
7. Log out and verify that the session is cleared. Re-login as another learner to demonstrate course/learner isolation.

## Troubleshooting and recovery

- **Moodle unavailable / invalid token / missing capability:** correct the local Moodle configuration or enrollment; quick login remains unavailable until `/auth/me` verifies the token.
- **SQL Server unavailable:** do not use a different or production target as a fallback. Restore the approved connection, then rerun startup checks.
- **Provider unavailable, timeout, rate limit, or invalid output:** the route returns its public-safe error and persists no untrusted Quiz or Flashcard artifact. Correct provider configuration and retry from the supported workflow.
- **Document not ACTIVE or stale provenance:** re-publish/select the current authorized document. Do not reuse stale context or source identifiers.
- **Launcher port conflict:** stop only the operator-owned conflicting process after identifying it, then rerun. The launcher intentionally terminates nothing.
- **Schema/deployment failure:** stop, preserve logs without credentials, verify the backup, and perform operator-approved rollback or forward recovery. No automatic data rewrite is supported.

## Post-deployment checks and rollback boundary

Verify login, course scoping, document publication, grounded chat, Quiz submission/grading, explanation, review batches, four card ratings, progress, recommendations, and logout with non-production test accounts. Check application logs for sanitized failures only. A source rollback is safe only when compatible with the observed additive schema; restore data only from the pre-deployment backup under an approved operational procedure.

Automated tests verify the application contracts; live Moodle, provider, SQL Server, and browser acceptance remain a separate operator approval.
