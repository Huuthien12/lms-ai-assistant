# Final live acceptance — security and regression

## Fresh execution

| JUnit artifact | Tests | Failures | Errors | Skips |
| --- | ---: | ---: | ---: | ---: |
| `final-focused-system.junit.xml` | 279 | 0 | 0 | 0 |
| `final-provider-publication.junit.xml` | 437 | 0 | 0 | 0 |
| `startup-order-regression.junit.xml` | 104 | 0 | 0 | 0 |

Both commands used `lms-dlu-demo\venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider` sequentially. The first covered identity, authorization, launcher/DPAPI policy, publication, chat, Quiz, post-Quiz review, progress, recommendations, and Streamlit AppTest. The second covered explanation, Quiz service/semantic grounding, provider error paths, grounded chat, Moodle adapters/trust/ingestion, publication, and Ledger V2.

```powershell
lms-dlu-demo\venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/test_demo_quick_login.py tests/test_demo_launcher_security.py tests/test_verified_identity.py `
  tests/test_learning_route_security.py tests/test_verified_publication.py `
  tests/test_verified_chat_integration.py tests/test_verified_learning_integration.py `
  tests/test_verified_learning.py tests/test_verified_learning_ui.py tests/test_quiz_lifecycle.py `
  tests/test_learning_generation_retry.py tests/ai/test_recommendation_service.py `
  --junitxml benchmark/reports/final-live-acceptance-2026-10-31/final-focused-system.junit.xml

lms-dlu-demo\venv\Scripts\python.exe -m pytest -q --tb=short -p no:cacheprovider `
  tests/ai/test_explanation_service.py tests/ai/test_quiz_semantic_grounding.py tests/ai/test_quiz_service.py `
  tests/ai/test_learning_provider.py tests/ai/test_demo_chat_provider.py tests/ai/test_deeptutor_provider.py `
  tests/ai/test_ollama_provider.py tests/ai/test_deepseek_provider.py tests/ai/test_q7_providers.py `
  tests/ai/test_grounded_chat.py tests/test_grounded_chat_router.py tests/test_moodle_adapter.py `
  tests/test_moodle_discovery_router.py tests/test_moodle_ingestion_router.py tests/test_moodle_ingestion_ledger.py `
  tests/test_moodle_ingestion_ledger_v2.py tests/deeptutor_integration/test_moodle_trust.py `
  --junitxml benchmark/reports/final-live-acceptance-2026-10-31/final-provider-publication.junit.xml
```

The two JUnit files in this directory are the fresh final-acceptance evidence.

## Security results

The fresh suite exercises missing/foreign/revoked authorization, private attempt/course guards, client-supplied score/identity/mastery rejection, answer-key privacy, ACTIVE/stale/deleted source rejection, forged context/source prevention, malformed provider output, timeout/rate-limit mapping, retry bounds, review-batch idempotency/pending behavior, write-failure rollback paths, and public-safe errors. Launcher tests verify loopback-only binding and no direct credential assignment; quick-login tests verify missing DPAPI material fails closed.

One real clean-database defect was found and fixed during this acceptance run: `ReviewBatches` could be created before its `QuizAttempts` foreign-key target. `f9411ef6` changes only router registration order and adds a focused regression guard. The corrected clean startup and restart passed against the approved isolated database. Final source/report publication still requires a staged secret scan and `git diff --cached --check`; `.env`, DPAPI material, JUnit artifacts, logs, runtime data, virtual environments, and pre-existing untracked benchmark data are excluded.

A separate read-only scan of all tracked files found no tracked `.env`, DPAPI, private-key, certificate, database, or SQLite artifact and no high-confidence private-key, AWS, GitHub, Slack, or Google API-key marker. The tracked `.env.example` contains blank placeholders only and explicitly directs operators to keep real secrets local.

## Limitations

Real isolated SQL startup/schema/restart and one synthetic local Ollama request were executed. No real Moodle workflow, approved learner identity, Moodle mutation, live browser interaction, or application-grounded provider generation was completed; those remain PENDING APPROVAL.

The focused 104-test JUnit was generated in the acceptance-only log directory for the fix verification and then removed during the authorized run cleanup; it was intentionally not published as a runtime artifact. The earlier fresh 279- and 437-test JUnit evidence remains separately recorded and excluded from Git.
