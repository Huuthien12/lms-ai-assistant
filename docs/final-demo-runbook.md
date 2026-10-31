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
3. **Streamlit-supported:** Generate a trusted Quiz, start an attempt, and submit answers. The backend derives grades from the stored definition; clients never submit a grade or answer key.
4. **Streamlit-supported:** Show deterministic grading and the grounded explanation. If current source validation makes an explanation unavailable, show that safe unavailable state rather than substituting an unverified answer.
5. **Streamlit-supported:** For an incorrect graded attempt, select **Ôn tập câu sai bằng Flashcard**, rate cards with AGAIN/HARD/GOOD/EASY, then show updated Progress and rule-first recommendations.
6. **API verification (optional):** Confirm the scoped `/learning` Quiz, review-batch, progress, and recommendations responses using the same personal Moodle credential. Do not use internal or operator routes for a student demonstration.

No quiz, mastery, recommendation, or flashcard graphical UI is claimed by this demo.
