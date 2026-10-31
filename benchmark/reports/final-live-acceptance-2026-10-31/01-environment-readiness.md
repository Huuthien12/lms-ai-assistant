# Final live acceptance — environment readiness

Date: 2026-10-31. Baseline verified: `origin/project-main` is `6b3b7eb5e21ee1acff190a19cc82d58f19160331` (PR #42), containing P5/P6/P7/P8 commits through `bbbf12f7e037ebf8e7c901f06de5d84eb5cb3cfb`. The acceptance worktree contains only pre-existing untracked artifacts; none were changed or selected for release.

| Dependency | Present/configured | Verified now | Safe test status |
| --- | --- | --- | --- |
| LMS Python venv | Present; Python 3.11.9 | FastAPI 0.143.3, Streamlit 1.66.0, pytest 9.1.1, httpx 0.28.1 import successfully; `pip check` passed | Safe automated tests complete |
| FastAPI / Streamlit entrypoints | `lms-dlu-demo/main.py`, `app.py`, and launcher present | Neither port 8001 nor 8502 was listening | Startup is **not authorized** because it can run schema initialization against protected SQL |
| Moodle | Local Docker `deeptutor-moodle` healthy on loopback | `GET /login/index.php` returned HTTP 200 without authentication | Login/course workflow needs approved test identity; no token used |
| Ollama | Process listening on loopback 11434 | `GET /api/tags` returned HTTP 200 | Real model call requires approved content/request budget |
| Groq | Process-level key presence only; value not inspected | Not invoked | Paid/provider acceptance requires approval |
| SQL Server tooling | `sqlcmd.exe` and `pyodbc` present | No connection attempted | Existing `LMS_DeepTutor` is protected; no database authorization |
| Moodle Docker database | Container healthy | Not accessed | Not an LMS SQL target and not touched |

The launcher source binds FastAPI and Streamlit to `127.0.0.1`, checks Moodle, the approved local SQL target, model/provider availability, port conflicts, and readiness endpoints. Its default-enabled demo chooser remains DPAPI-backed, fails closed, and still calls `/auth/me`. These properties are verified by fresh launcher/quick-login tests, not a real launcher startup.

## Approved isolated execution performed

The operator approved `localhost` / default `MSSQLSERVER` and new database `codex_final_acceptance_20261031_a249d036f0ed`. Before creation, `master` confirmed that exact database was absent and distinct from `LMS_DeepTutor`; the database was then created. FastAPI schema initialization ran only against it. The expected Quiz, Flashcard, ReviewBatch, LearningEvent, TopicMastery, and verified-artifact tables exist, and all ten business tables had zero rows after startup and restart.

FastAPI (`main:app`) started on `127.0.0.1:8001` and Streamlit (`app.py`) on `127.0.0.1:8502` with process-scoped isolated database, upload, and DeepTutor runtime paths. Both `/openapi.json` and `/_stcore/health` returned HTTP 200 before and after an authorized stop/restart cycle. The first clean-database startup exposed a schema-order defect: `ReviewBatches` was initialized before `QuizAttempts`. Fix `f9411ef6e12b13b0a502ce14567674a462414a8e` registers Quiz and Flashcard schema routers before verified-learning schema initialization; clean startup then passed.

The local Moodle container is loopback-bound and its login page is reachable. Both existing secure local credentials were denied `core_webservice_get_site_info` with `accessexception`; no Moodle user, course, enrollment, document, or permission was mutated. This is an administration-access blocker, not an authorization bypass opportunity.

Ollama `qwen2.5:3b` is installed and one approved synthetic availability request returned exactly `OK`, within the 60-second limit. No Groq, fallback, private content, or model-persisted application artifact was used.

Cleanup completed: only the verified acceptance FastAPI and Streamlit processes were stopped; ports 8001 and 8502 were released; `codex_final_acceptance_20261031_a249d036f0ed` was dropped only after master-session identity checks; and the uniquely named acceptance upload/log directories were removed. No runtime directory existed, and no unrelated database, Moodle resource, process, or worktree was changed.
