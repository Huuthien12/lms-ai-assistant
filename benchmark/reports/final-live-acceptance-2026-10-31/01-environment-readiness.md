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

Approval required for live execution: authorize one isolated writable SQL database or explicitly named safe test database; approved Moodle student/lecturer test identities; allowed test course/document dataset; a bounded provider budget/content boundary; and permission to start/restart FastAPI and Streamlit pointed only at that isolated target. Rollback: stop the operator-started processes and drop/restore only the explicitly approved isolated database according to the operator procedure; no production target may be used.
