# Final demo runbook — operator-approved environment only

1. Confirm the target is the approved isolated SQL test database, not `LMS_DeepTutor`; back it up/snapshot it first.
2. Confirm approved Moodle test identities, a safe enrolled course, and an ACTIVE test document. Provision any demo chooser account locally with `lms-dlu-demo\provision_demo_accounts.ps1`; never copy a token or DPAPI blob into the repository.
3. Confirm Moodle and provider availability. For an isolated acceptance database, do **not** use `start_lms.bat`: it intentionally enforces `LMS_DeepTutor`. Start FastAPI and Streamlit directly with process-scoped `LMS_DB_NAME`, `LMS_UPLOAD_DIR`, and `DEEPTUTOR_RUNTIME_DIR` set to unique acceptance-only paths; bind only `127.0.0.1:8001` and `127.0.0.1:8502`.
4. Confirm `/openapi.json` and `/_stcore/health`, then sign in. The chooser is not authentication bypass: it must verify `/auth/me`.
5. Demonstrate authorized course selection, ACTIVE document, grounded Tutor citations, a grounded Quiz, one incorrect submission, deterministic grade and explanation.
6. Select **Ôn tập câu sai bằng Flashcard**, verify a READY batch and an idempotent repeat, then review AGAIN/HARD/GOOD/EASY.
7. Open Progress and recommendations, explain the rule-first result, then logout and verify session cleanup.
8. If any provider/source/schema error appears, show the public-safe error. Do not retry by using a private source, internal route, or another learner identity.
9. Stop only the FastAPI/Streamlit processes started for this demo. Preserve sanitized logs, restore/clean only the approved isolated database, and record the outcome.

Troubleshooting: Moodle/auth failure requires a valid approved personal token and enrollment; unavailable provider requires operator configuration correction; inactive source must be re-published through an authorized workflow; occupied ports must be identified before retry because the launcher deliberately kills nothing. A schema error or DB target ambiguity is a stop condition, not a reason to point at production.
