# Current AI integration contract

This document describes the implemented AI core. Mocked tests verify contracts,
not live Moodle, DeepTutor, Ollama or DeepSeek quality/availability.

## Provider policy

`build_default_orchestrator` uses Ollama directly without a nonblank DeepSeek
key; otherwise DeepSeek is primary with Ollama fallback for HTTP 429/500/502/503/504,
timeout/network, rate-limit or service-unavailable errors. Other failures do not
trigger fallback. Default Ollama is localhost port 11434, model `qwen2.5:3b`.
Attempted fallback sets `fallback_used=true` even on failure; final provider/model
identify the producing provider. Error bodies/exceptions are sanitized.
DeepSeek health checks configuration only, not live connectivity.

## Grounded chat

`POST /chat/grounded` receives `question`, `course_id`, optional `kb_name`;
strings are trimmed and blanks rejected. The route calls the public DeepTutor
query contract and passes only retrieved source content to GroundedChatService.
Returned course must match the request and returned KB must match the server-resolved
course-to-KB mapping before AI use. Explicit caller KB names remain subject to
DeepTutor's mapping check; they are not ownership proof. Envelope shape and
explicit source course/KB identity conflicts fail closed. Missing per-source
provenance identity remains an upstream dependency. Document provenance/lifecycle
is not yet verified. These checks do not provide end-user authorization; Q5 remains
blocked on verified identity and course access, and full Q6 provenance remains blocked.

Response fields are `status`, `answer`, `course_id`, `kb_name`, `sources`, and
`ai` (`provider`, `model`, `fallback_used`). Structured sources originate from
retrieval, never model output. Empty usable context returns a safe answer without
a provider call. Provider error results preserve HTTP 200/status error with an
empty answer; raised/malformed chat results return sanitized HTTP 502.
Free-form answer claims and citation text are **not semantically verified**.
Slide/section are not added to the public citation schema.

## Quiz, explanation and flashcards

- Grounded quiz takes topic, count 1–20, difficulty, `question_types=["mcq"]`,
  nonblank retrieved context and optional caller sources. Internal questions
  retain answer key/explanation; public output includes only question/type/options.
  Duplicate normalized questions and option texts, duplicate option IDs, invalid
  keys/count/schema are rejected. Caller assigns persistent question IDs.
- Explanation takes question, selected-answer text or null, authoritative
  correct-answer text, context and caller sources. It never re-grades; output
  is status/explanation/key_concept/sources. Missing context raises
  `INSUFFICIENT_GROUNDED_CONTEXT`. Shared review workflow reports
  `explanation_status="unavailable"` when trusted context is unavailable.
- Grounded flashcards take topic, count 1–50, difficulty, context and sources.
  Output front/back/topic/difficulty uses trusted requested topic/difficulty.
  Duplicate normalized front/back pairs are rejected; sharing just one side is
  allowed. Generation is not learning evidence; a real caller review is required.

Normalization for duplicate checks case-folds and collapses whitespace. Sources
accept null, a dict, or list of dicts, are copied, and never come from the model.
Malformed provider objects yield safe generation failures; successful provider
output with invalid JSON/schema yields the corresponding schema error.
Legacy quiz/flashcard prompt interfaces remain non-grounded and are not the
grounded workflow. Semantic factual quality remains prompt-enforced.

## Mastery

`calculate_mastery(student_id, course_id, topic, evidence)` requires exact scope
on every item; mixed scope is rejected, not filtered. Quiz evidence requires an
actual bool `correct`; flashcard ratings map AGAIN/HARD/GOOD/EASY to 0/0.4/0.75/1.
Quiz accuracy and mean review score combine with 0.8/0.2 weights when both exist;
otherwise use the available component. Percentage is rounded to two decimals.
Levels: <50 WEAK, <70 DEVELOPING, <85 GOOD, otherwise MASTERED. Confidence from
count: <5 LOW, 5–14 MEDIUM, >=15 HIGH. Chat/material opens do not imply mastery.
Empty evidence returns score/level null, confidence LOW, evidence_count 0.
Output preserves scope and component scores/counts; inputs are not mutated.

## Recommendations and identity

Input requires topic, numeric finite score 0–100, confidence and evidence_count;
available topics are caller strings and deadline is an optional nonblank string.
Count <2 or LOW confidence takes precedence: REVIEW_TOPIC/EASY_QUIZ.
Otherwise WEAK: review/flashcards/easy quiz; DEVELOPING: review/medium quiz;
GOOD: medium/hard quiz; MASTERED: next topic/hard quiz.
Output preserves deterministic topic/score/level/confidence/count/actions/deadline,
plus message and message_source. Only JSON with one nonblank string `message`
is accepted from LLM; malformed/provider failure uses a local rule message.
Message prose is not semantically verified. Empty mastery is rejected, not
converted to score zero. Dates are not interpreted or invented.

Core identity is `student_id`; no user_id mapping is implemented here.
Recommendation items do not carry student/course fields. Existing API wrappers
bind requested student/course to snapshot lookup and response envelope; ownership,
authentication/enrollment and user-to-student mapping remain shared responsibilities.

## Demo and evaluation limits

Per [final demo runbook](final-demo-runbook.md), trusted quiz registration,
attempt/submit/review, progress/recommendation and optional trusted flashcard
registration/review are API-only. No graphical UI for these features is claimed.
Persistence demonstrations require SQL Server; AI-core tests do not prove them.

`tests/ai/test_ai_evaluation_matrix.py` covers mocked English and Vietnamese
grounded questions, no source, wrong course/source scope, fabricated citation
text (structured sources protected, prose unverified), provider error/fallback,
malformed provider result and scoped recommendation API delegation without DB.
Other provider tests cover malformed HTTP responses. These are regression cases,
not a live retrieval evaluation or semantic hallucination classifier.
