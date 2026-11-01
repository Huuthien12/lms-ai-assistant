# DeepTutor Verified UI Design System

## Intent

DeepTutor is a calm, evidence-led learning workspace. The interface should make the current course, trustworthy source status, and next learning action obvious without turning technical identifiers or AI internals into visual noise.

This document governs the Streamlit presentation layer only. It must not change verified identity, course scope, ACTIVE publication, Quiz answer-key privacy, learning API contracts, or `app.py`'s guarded verified entrypoint.

## Visual direction

- **Character:** scholarly, clear, and quietly confident; software for focused study rather than a marketing dashboard.
- **Structure:** a dark indigo course rail, a pale blue-white work canvas, one strong learning action per view, and compact evidence/status cues.
- **Hierarchy:** title → current task → verified evidence/status → supporting detail. Do not present raw course keys, source hashes, tokens, or internal IDs to learners.
- **Density:** generous page rhythm, concise cards, and no nested-card stacks. Use an empty state when data does not exist.

## Tokens

| Role | Token | Value |
| --- | --- | --- |
| Brand / primary action | `primary` | `#1565C0` |
| Primary hover / rail depth | `primary-dark` | `#0D47A1` |
| Selected / informational surface | `primary-light` | `#E3F2FD` |
| Canvas | `background` | `#F6F8FB` |
| Raised surface | `surface` | `#FFFFFF` |
| Primary text | `text-primary` | `#1F2937` |
| Supporting text | `text-muted` | `#64748B` |
| Verified / success | `success` | `#16A34A` |
| Caution | `warning` | `#F59E0B` |
| Error | `error` | `#DC2626` |

Use system UI sans-serif. Headings use modest negative tracking (`-0.02em`), 700–750 weight, and short Vietnamese labels. Keep body copy at 14–16px with 1.45–1.55 line height. Use 4/8/12/16/24/32px spacing steps, 14–16px card radii, and 999px only for small status chips.

## Components

| Component | Required behavior |
| --- | --- |
| Login / account selection | Explain Moodle-verified session status. Demo quick login remains a DPAPI-backed local convenience, not an identity bypass. Never display a token or account secret. |
| Course shell | Sidebar shows product identity, current authorized course selector, and logout. The selected course uses its learner-facing verified name; raw keys remain internal. |
| ACTIVE document row | File icon, supplied title/type, compact `ACTIVE` status, and truthful empty/error states. Do not expose version/hash unless a staff-only diagnostic view already authorizes it. |
| Tutor message | Clearly distinguish learner and assistant messages; render citation titles immediately below the cited answer. A missing/invalid source is an error state, not a fabricated answer. |
| Quiz | One question at a time visually, readable option hit areas, selected state, and an explicit submitted/graded state. Public UI never renders correct keys before submit. Failed grounding is a concise recoverable state. |
| Quiz feedback | Correct/incorrect state, source-grounded explanation after grading only, and a clear next action. Preserve answer privacy in all error and loading states. |
| Flashcard review | Single calm card face, visible progress count, and four equal-footprint AGAIN/HARD/GOOD/EASY controls. Disable only while the existing request is active; no duplicate submission on rerun. |
| Progress / mastery | Use truthful computed values and recommendation status. Empty state says what activity creates data; never invent streaks, percentages, or recommendations. |

## Interaction & accessibility rules

- Retain native Streamlit controls wherever possible; label all inputs and use visible keyboard focus.
- Maintain 44–48px minimum button height for primary learning actions and review ratings.
- Use explicit `background`, `border-color`, `color`, and `transform` transitions only; honor reduced motion.
- Pair status color with text/icon; do not rely on color alone.
- Keep desktop rail responsive: below 850px, collapse/reflow rather than hiding current course, status, or primary task.
- Long document and course titles wrap or truncate safely; learner content must not overflow cards.

## Screen direction

1. **Login:** centered verification card, optional demo-account expander, clear Moodle-token path, no decorative distraction.
2. **Dashboard / course:** selected course as the anchor; one next-learning summary, then documents and recent learning state.
3. **Documents:** strong `ACTIVE` count, compact document rows, staff-only sync affordances retained exactly as guarded today.
4. **Tutor:** conversation-led canvas, citation note directly below answers, source-unavailable errors in-place.
5. **Quiz:** explicit scope and count controls, calm question card, answer feedback only after the existing submit/grade lifecycle.
6. **Flashcards:** review-first layout; generation and unavailable-provenance states are separate from manual-card browsing.
7. **Progress:** one clear learning summary, then mastery/recommendations; no dashboard-card overload.

## Implementation guardrails

- Consolidate presentation changes in `lms-dlu-demo/ui/theme.py`, `ui/components.py`, and `verified_learning_ui.py` only when needed.
- Preserve `lms-dlu-demo/app.py:50–52` and do not revive or edit the legacy code below `st.stop()` as part of the verified UI polish.
- Use current Streamlit layout primitives, existing `show_error`, `render_citations`, and session-state keys. Do not add React, Next.js, or a second frontend.
- Any new visual state must be backed by existing server data; never infer authorization, source status, scores, or mastery client-side.
