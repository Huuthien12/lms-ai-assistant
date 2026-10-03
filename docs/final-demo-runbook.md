# Final Demo Runbook

## Prerequisites

- Use the LMS Python environment and the DeepTutor environment.
- Start Ollama with `qwen2.5:3b` and `nomic-embed-text` available.
- Configure `MOODLE_BASE_URL` and `MOODLE_TOKEN` locally; do not commit them.
- SQL Server is required only for quiz, mastery, progress, recommendation, and flashcard persistence demonstrations.
- Keep `USE_MOCK_API=false` (or unset it) for the real demo.

## Startup and readiness

1. Start Ollama.
2. Start the LMS backend with `lms-dlu-demo\start_lms.bat`.
3. Optionally start Streamlit through that launcher.
4. Check `GET /health/ready`, then `GET /lms/ready`.

The confirmed course mapping is `INT1339` -> `int1339-python`. Its existing indexed content should be reused; do not ingest it again for the demo.

## Demo sequence

1. **Streamlit-supported:** Select `INT1339` and ask a question. Streamlit sends `POST /lms/chat` with `question` and `course_id`.
2. Show the grounded answer, source titles, KB name, and provider/model metadata. The real path is `/lms/chat` -> `/chat/grounded` -> DeepTutor retrieval -> grounded provider.
3. **API-only:** Register a trusted quiz, start an attempt, and submit answers.
4. **API-only:** Show deterministic grading and `GET /quiz-attempts/{attempt_id}/review`; unavailable explanations must remain explicitly unavailable.
5. **API-only:** Show `GET /courses/{course_id}/progress` and `GET /courses/{course_id}/recommendations`.
6. **API-only, optional:** Register and review a trusted flashcard, then show updated progress.

No quiz, mastery, recommendation, or flashcard graphical UI is claimed by this demo.
