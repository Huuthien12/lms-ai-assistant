# C2C | QUAN | FINAL P6-P8 CLOSEOUT

Execution date: 2026-10-16 (Asia/Saigon).

## Git and scope

| Item | Value |
|---|---|
| Required base | `origin/project-main` |
| Fetched base SHA | `e14a45a471b317ce998d44a7833982764e7ea353` |
| Branch | `codex/quan-final-p8` |
| Worktree | Dedicated managed worktree created from the fetched base |
| Merge performed | No |
| Live Quiz or benchmark campaign run | No |
| Model or timeout defaults changed | No |

The base already contains the integrated Quiz semantic-grounding and sanitized
observability fixes from PR #38. This lane keeps that contract and closes the
remaining Flashcard semantic-grounding and small multi-provider benchmark gaps.

## P6 Quiz and Flashcard result

Quiz was reverified without weakening its extractive-cloze contract. The
production path accepts only a private answer key that is deterministically
supported by a contiguous excerpt of the supplied verified context. Public
projection omits the key, explanation, grounding evidence, source metadata and
provider internals. Grading remains deterministic and performs zero provider
calls. Existing duplicate-attempt/submission/event and transaction tests pass.

Flashcard now enforces the same deterministic grounding shape:

1. `grounding_evidence` must be a non-empty contiguous excerpt of the supplied
   verified context.
2. `back_text` must occur exactly once in that excerpt.
3. `front_text` must equal the canonical prompt plus the excerpt with that one
   answer span replaced by `____`.
4. Every card is validated before the batch is returned. One unsupported card
   rejects the whole batch, so persistence is not reached.
5. The public allowlist contains only `front_text`, `back_text`, `topic` and
   `difficulty`. The verified-learning integration continues to persist the
   trusted owner/course context and source version while omitting private
   grounding evidence from the learner response.
6. The legacy non-grounded API remains compatible and is never represented as
   grounded output.

Authorization, ACTIVE-source eligibility, course isolation and lifecycle
revalidation remain owned by the verified integration boundary. Generation
still receives only the verified context issued by that boundary; the AI
services do not perform a second retrieval.

## P7 security and persistence evidence

Automated coverage verifies the following for Quiz and Flashcard:

- unauthorized owner/course generation is denied before retrieval, provider or
  persistence;
- one course cannot consume another course's context or learning evidence;
- empty, stale, deleted or superseded source context is rejected or replaced
  before provider use;
- provider/schema/semantic failure does not create a trusted partial artifact;
- Quiz keys, explanations and evidence do not cross the public boundary;
- Flashcard grounding evidence, source metadata and provider fields do not
  cross the public boundary;
- grading uses persisted server keys, rejects forged client score/key fields
  and performs no provider call;
- duplicate submit and duplicate review/event paths are idempotent or return
  their controlled conflict without duplicating evidence.

## P8 benchmark harness

`backend/services/ai/benchmark_harness.py` is deliberately separate from the
student workflow and repositories. It creates the existing `QuizService` or
`FlashcardService` around each configured `LLMProvider`, runs targets
sequentially with the same immutable fixture and `temperature=0`, and uses the
production structural and semantic validators. It never creates a Quiz,
attempt, Flashcard, answer or learning-evidence record.

The harness accepts only `SyntheticBenchmarkSource` values. It validates the
fixture course against every source, requires ACTIVE status, verifies the
content hash, derives source metadata internally, and rejects arbitrary
production context strings or caller-supplied metadata before invoking any
provider. Provider/model report labels come from a static allowlist. Raw
identifiers returned by a provider are never copied into the report.

Each result has the same schema:

- `provider`, `model`;
- `status` and sanitized `failure_category`;
- `structured_output_valid`;
- `grounding_pass_rate` (`1.0` for a fully accepted batch and `0.0` for a
  rejected batch; `null` when the provider produced no evaluable output);
- `total_latency_ms`;
- `first_token_latency_ms` when exposed by the provider, otherwise `null`;
- normalized prompt/completion/total token usage when available, otherwise
  `null`;
- estimated USD cost when both token usage and caller-supplied prices are
  available, otherwise `null`.

Provider content, prompts, synthetic context, exception text and credentials are
never included in the report. One target failure is caught and recorded without
stopping later targets. Tests cover two provider/model configurations, identical
calls, Quiz and Flashcard contracts, provider failure isolation, structural
versus semantic categories, latency/usage/cost fields and secret suppression.

Minimal caller setup is:

```python
import asyncio
import json
import os

from backend.services.ai.benchmark_harness import (
    BenchmarkFixture,
    BenchmarkHarness,
    BenchmarkTarget,
    SyntheticBenchmarkSource,
)
from backend.services.ai.deepseek_provider import DeepSeekProvider
from backend.services.ai.ollama_provider import OllamaProvider

fixture = BenchmarkFixture(
    task="quiz",
    course_id="INT1339",
    topic="Python",
    count=5,
    difficulty="medium",
    sources=(SyntheticBenchmarkSource(
        course_id="INT1339",
        source_id="synthetic-python-v1",
        content=synthetic_public_context,
    ),),
)
targets = [
    BenchmarkTarget(OllamaProvider(model="qwen2.5:3b")),
    BenchmarkTarget(
        DeepSeekProvider(os.environ["DEEPSEEK_API_KEY"], model="deepseek-chat")
    ),
]
report = asyncio.run(BenchmarkHarness().run(fixture, targets))
print(json.dumps(report, indent=2))
```

Additional provider/model pairs participate through the existing `LLMProvider`
interface after their static public identity is added to the harness allowlist.
Secrets stay in provider configuration and are not part of the result.

## Verification

| Check | Result |
|---|---|
| Regression-first check before implementation | Expected RED: missing Flashcard grounding contract and benchmark module |
| New Flashcard-grounding and benchmark regression files | **17 passed** |
| Focused Quiz/Flashcard/security/persistence/benchmark suite | **266 passed**, 39 warnings |
| Full `tests/` suite excluding unavailable Streamlit UI module | **1102 passed + 16 subtests**, 58 warnings |
| Python compile check for changed/new modules and tests | **PASS** |
| Dependency consistency | **PASS: 60 packages compatible** |
| Diff whitespace check | **PASS** |
| Ruff / mypy / pyright | Not configured or installed in this checkout |
| Streamlit UI suite | Not run: `streamlit` is not installed in the supplied environment |
| Live provider/model campaign | Intentionally not run by this lane |

Reproduction commands:

```powershell
$env:PYTHONPATH='C:\lms-ai-assistant\.venv\compat'
& 'C:\lms-ai-assistant\.venv\Scripts\python.exe' -m pytest -q `
  tests\ai\test_flashcard_semantic_grounding.py `
  tests\ai\test_benchmark_harness.py `
  tests\ai\test_flashcard_service.py `
  tests\ai\test_quiz_semantic_grounding.py `
  tests\ai\test_quiz_service.py `
  tests\ai\test_ai_integration_acceptance.py `
  tests\test_verified_learning.py `
  tests\test_verified_learning_integration.py
& 'C:\lms-ai-assistant\.venv\Scripts\python.exe' -m pytest -q tests `
  --ignore=tests\test_verified_learning_ui.py
uv pip check --python 'C:\lms-ai-assistant\.venv\Scripts\python.exe'
```

## Known limitations and handoff boundary

No live model was asked to satisfy the stricter Flashcard extractive contract in
this lane. A model that does not follow it will fail closed with a controlled
generation error instead of persisting unsupported cards. First-token latency
is `null` for the current non-streaming providers unless a provider exposes that
measurement. Cost is `null` until the caller supplies prices. These are live
acceptance/configuration actions, not remaining implementation.

Thiện can select provider/model targets, execute the live benchmark, and
aggregate the returned metrics. No production/live benchmark campaign, live
Quiz mutation, merge, or project-main update was performed here.

## Benchmark security correction

Candidate base `239f887ef17ecfda79c70739eacc17bed420869e` was reviewed on
2026-10-16. The benchmark no longer accepts arbitrary context strings or source
metadata. It accepts only ACTIVE `SyntheticBenchmarkSource` instances, checks
course consistency and content hashes again at run time, and derives provider
input metadata from those immutable fields. Cross-course, inactive and
inconsistent sources fail before any provider call.

Provider/model labels now come from a static allowlist and are revalidated at
run time. Raw identities in successful or failed `LLMResult` objects are
ignored. Regression tests prove that `sk-private-token` is absent from both
serialized reports and controlled error output.

Current correction verification: benchmark security **14 passed**; focused
benchmark/Flashcard persistence/deterministic grading security **262 passed**
with 39 warnings; full backend/domain suite **1109 passed + 16 subtests** with
58 warnings. Live Moodle/runtime acceptance and a live provider benchmark remain
unverified and were not run as part of this correction.
