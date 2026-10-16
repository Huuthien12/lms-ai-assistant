"""Small, persistence-free benchmark runner for grounded learning generation."""
from copy import deepcopy
from dataclasses import dataclass
import re
import time
from typing import Any, Dict, List, Optional, Sequence

from backend.services.ai.flashcard_service import (
    FlashcardService,
    _FlashcardSemanticValidationError,
)
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.quiz_service import QuizService, _QuizSemanticValidationError


_SAFE_IDENTITY = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _safe_identity(value: Any) -> str:
    return value if isinstance(value, str) and _SAFE_IDENTITY.fullmatch(value) else "unknown"


def _optional_nonnegative(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


@dataclass(frozen=True)
class BenchmarkFixture:
    """One immutable input contract reused for every configured target."""

    task: str
    topic: str
    count: int
    difficulty: str
    verified_context: str
    source_metadata: Any = None

    def __post_init__(self) -> None:
        maximum = 20 if self.task == "quiz" else 50 if self.task == "flashcard" else 0
        valid_sources = (
            self.source_metadata is None
            or isinstance(self.source_metadata, dict)
            or (isinstance(self.source_metadata, list)
                and all(isinstance(item, dict) for item in self.source_metadata))
        )
        if (maximum == 0
                or not isinstance(self.topic, str) or not self.topic.strip()
                or type(self.count) is not int or not 1 <= self.count <= maximum
                or self.difficulty not in ("easy", "medium", "hard", "mixed")
                or not isinstance(self.verified_context, str)
                or not self.verified_context.strip()
                or not valid_sources):
            raise ValueError("invalid benchmark fixture")
        object.__setattr__(self, "topic", self.topic.strip())
        object.__setattr__(self, "source_metadata", deepcopy(self.source_metadata))


@dataclass(frozen=True)
class BenchmarkTarget:
    """A provider/model instance plus optional public token prices in USD."""

    provider: Any
    input_cost_per_million: Optional[float] = None
    output_cost_per_million: Optional[float] = None

    def __post_init__(self) -> None:
        if self.provider is None:
            raise ValueError("invalid benchmark target")
        for value in (self.input_cost_per_million, self.output_cost_per_million):
            if value is not None and _optional_nonnegative(value) is None:
                raise ValueError("invalid benchmark target")


class _RecordingProvider:
    def __init__(self, provider: Any):
        self._provider = provider
        self.provider = getattr(provider, "provider", "unknown")
        self.model = getattr(provider, "model", "unknown")
        self.result: Optional[LLMResult] = None

    async def generate(self, prompt: str, system_prompt: Optional[str] = None,
                       **kwargs: Any) -> LLMResult:
        result = await self._provider.generate(prompt, system_prompt, **kwargs)
        if isinstance(result, LLMResult):
            self.result = result
        return result

    async def health_check(self) -> Dict[str, Any]:
        return await self._provider.health_check()


class BenchmarkHarness:
    """Run targets sequentially so one failure cannot abort or skew peer runs."""

    @staticmethod
    def _usage(result: Optional[LLMResult]) -> Optional[Dict[str, Optional[int]]]:
        raw = result.usage if isinstance(result, LLMResult) else None
        if not isinstance(raw, dict):
            return None
        usage = {
            field: raw.get(field) if type(raw.get(field)) is int and raw[field] >= 0 else None
            for field in _USAGE_FIELDS
        }
        return usage if any(value is not None for value in usage.values()) else None

    @staticmethod
    def _cost(target: BenchmarkTarget,
              usage: Optional[Dict[str, Optional[int]]]) -> Optional[float]:
        if (usage is None or target.input_cost_per_million is None
                or target.output_cost_per_million is None
                or usage["prompt_tokens"] is None
                or usage["completion_tokens"] is None):
            return None
        return round(
            (usage["prompt_tokens"] * target.input_cost_per_million
             + usage["completion_tokens"] * target.output_cost_per_million) / 1_000_000,
            10,
        )

    async def _run_target(self, fixture: BenchmarkFixture,
                          target: BenchmarkTarget) -> Dict[str, Any]:
        recording = _RecordingProvider(target.provider)
        orchestrator = AIOrchestrator(recording)
        status = "success"
        category = None
        structured: Optional[bool] = True
        grounding_rate: Optional[float] = 1.0
        started = time.monotonic()
        try:
            if fixture.task == "quiz":
                await QuizService(orchestrator).generate_grounded_quiz(
                    topic=fixture.topic,
                    question_count=fixture.count,
                    difficulty=fixture.difficulty,
                    question_types=["mcq"],
                    retrieved_context=fixture.verified_context,
                    source_metadata=deepcopy(fixture.source_metadata),
                    client_facing=False,
                    temperature=0,
                )
            else:
                await FlashcardService(orchestrator).generate_grounded_flashcards(
                    topic=fixture.topic,
                    count=fixture.count,
                    difficulty=fixture.difficulty,
                    retrieved_context=fixture.verified_context,
                    source_metadata=deepcopy(fixture.source_metadata),
                    temperature=0,
                )
        except (_QuizSemanticValidationError, _FlashcardSemanticValidationError):
            status, category, structured, grounding_rate = (
                "failure", "grounding_failure", True, 0.0,
            )
        except ValueError as error:
            status = "failure"
            code = str(error)
            if code in ("QUIZ_GENERATION_FAILED", "FLASHCARD_GENERATION_FAILED"):
                category, structured, grounding_rate = "provider_failure", None, None
            elif code.startswith(("INVALID_QUIZ_SCHEMA", "INVALID_FLASHCARD_SCHEMA")):
                category, structured, grounding_rate = "structural_failure", False, 0.0
            else:
                category, structured, grounding_rate = "invalid_request", None, None
        except Exception:
            status, category, structured, grounding_rate = (
                "failure", "internal_failure", None, None,
            )
        elapsed_ms = (time.monotonic() - started) * 1000
        result = recording.result
        provider = result.provider if result is not None else recording.provider
        model = result.model if result is not None else recording.model
        usage = self._usage(result)
        first_token = _optional_nonnegative(
            getattr(result, "first_token_latency_ms", None) if result is not None else None
        )
        return {
            "provider": _safe_identity(provider),
            "model": _safe_identity(model),
            "status": status,
            "failure_category": category,
            "structured_output_valid": structured,
            "grounding_pass_rate": grounding_rate,
            "total_latency_ms": round(max(0.0, elapsed_ms), 3),
            "first_token_latency_ms": first_token,
            "token_usage": usage,
            "estimated_cost_usd": self._cost(target, usage),
        }

    async def run(self, fixture: BenchmarkFixture,
                  targets: Sequence[BenchmarkTarget]) -> Dict[str, Any]:
        if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) or not targets:
            raise ValueError("invalid benchmark targets")
        if any(not isinstance(target, BenchmarkTarget) for target in targets):
            raise ValueError("invalid benchmark targets")
        results: List[Dict[str, Any]] = []
        for target in targets:
            results.append(await self._run_target(fixture, target))
        return {
            "fixture": {
                "task": fixture.task,
                "topic": fixture.topic,
                "count": fixture.count,
                "difficulty": fixture.difficulty,
            },
            "results": results,
        }
