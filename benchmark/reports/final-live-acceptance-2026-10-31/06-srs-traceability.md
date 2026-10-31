# P4–P8 SRS traceability matrix

| Requirement | Description | Implementation location | Automated evidence executed now | Live/manual evidence | Status / remaining approval |
| --- | --- | --- | --- | --- | --- |
| BR-03, BR-05 | READY KB and no cross-course retrieval | `deeptutor_integration/`, `verified_learning_router.py` | Publication/chat/integration tests | None | PASS automated; live PENDING APPROVAL |
| FR-16, FR-17; BR-07–BR-10 | Provider abstraction/fallback and bounded failures | `backend/services/ai/`, `learning_generation.py` | Provider, retry, grounded-chat tests | Ollama health only | PASS automated; real provider PENDING APPROVAL |
| FR-18, FR-19; BR-12–BR-14, BR-19 | Grounded private Quiz generation | `quiz_lifecycle.py`, `learning_generation.py` | Quiz semantic/service and verified-learning tests | None | PASS automated; writable live test PENDING APPROVAL |
| FR-20; BR-15, BR-16, BR-35 | Deterministic one-time submit/grading | `quiz_lifecycle.py`, `grading_service.py` | Lifecycle/integration tests | None | PASS automated; persistence PENDING APPROVAL |
| FR-21; BR-17, BR-18 | Grounded wrong-answer explanation | `explanation_service.py` | Explanation/integration tests | None | PASS automated; real provider PENDING APPROVAL |
| FR-22; BR-21–BR-23 | Grounded Flashcards and owner-only review | `learning_generation.py`, `verified_learning_repository.py` | Review batch/UI/integration tests | None | PASS automated; real SQL PENDING APPROVAL |
| FR-23; BR-24–BR-27 | Scoped progress/mastery evidence | `learning_evidence.py`, `mastery_service.py` | Verified-learning/recommendation tests | None | PASS automated; restart PENDING APPROVAL |
| FR-24; BR-28 | Rule-first recommendations | `recommendation_service.py`, `verified_learning_router.py` | Recommendation/integration/UI tests | None | PASS automated; live user evidence PENDING APPROVAL |
| BR-29–BR-33 | Server authorization/privacy/no hard-coded or logged credentials | identity/router/quick-login modules | Identity, route-security, launcher, UI tests | No credentials inspected | PASS automated; live identity PENDING APPROVAL |
| BR-34, BR-36 | Duplicate prevention/idempotent writes | publication/repository modules | Publication, review batch, retry tests | Historical P6 SQL only | PASS automated; fresh real SQL PENDING APPROVAL |
| NFR-06–NFR-12 | Graceful failure, consistency, privacy, auditability, bounded AI use | AI services and validated routes | Provider/grounding/error tests | No live provider | PASS automated; operational validation PENDING APPROVAL |

No requirement identifier has been invented: IDs are taken from `docs/srs/01-system-overview.md` and `docs/srs/09-business-rules.md`. “PASS automated” is intentionally not a live acceptance claim.
