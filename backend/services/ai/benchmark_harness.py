"""Persistence-free benchmark runner restricted to synthetic benchmark data."""
from dataclasses import dataclass, field
from hashlib import sha256
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.services.ai.flashcard_service import (
    FlashcardService,
    _FlashcardSemanticValidationError,
)
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.quiz_service import QuizService, _QuizSemanticValidationError


_SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_USAGE_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")
_TRUSTED_TARGET_IDENTITIES = {
    ("ollama", "qwen2.5:3b"): ("ollama", "qwen2.5:3b"),
    ("deepseek", "deepseek-chat"): ("deepseek", "deepseek-chat"),
    ("gemini", "gemini-2.5-flash"): ("gemini", "gemini-2.5-flash"),
    ("fallback", "provider-chain"): ("fallback", "provider-chain"),
}


def _optional_nonnegative(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    return None


@dataclass(frozen=True)
class SyntheticBenchmarkSource:
    """Synthetic-only source; production retrieval context is not accepted here."""

    course_id: str
    source_id: str
    content: str
    version: str = "synthetic-v1"
    status: str = "ACTIVE"
    content_sha256: Optional[str] = None

    def __post_init__(self) -> None:
        valid_identity = all(
            isinstance(value, str) and _SAFE_SOURCE_ID.fullmatch(value)
            for value in (self.course_id, self.source_id, self.version)
        )
        if (not valid_identity or self.status != "ACTIVE"
                or not isinstance(self.content, str) or not self.content.strip()
                or len(self.content) > 200000):
            raise ValueError("invalid synthetic benchmark source")
        digest = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_sha256 is not None and self.content_sha256 != digest:
            raise ValueError("invalid synthetic benchmark source")
        object.__setattr__(self, "content_sha256", digest)

    def metadata(self) -> Dict[str, str]:
        return {
            "course_id": self.course_id,
            "source_id": self.source_id,
            "version": self.version,
            "status": "ACTIVE",
            "classification": "SYNTHETIC",
            "content_sha256": self.content_sha256 or "",
        }


@dataclass(frozen=True)
class BenchmarkFixture:
    """One immutable synthetic input contract reused for every target."""

    task: str
    course_id: str
    topic: str
    count: int
    difficulty: str
    sources: Tuple[SyntheticBenchmarkSource, ...]

    def __post_init__(self) -> None:
        maximum = 20 if self.task == "quiz" else 50 if self.task == "flashcard" else 0
        if (maximum == 0
                or not isinstance(self.course_id, str)
                or not _SAFE_SOURCE_ID.fullmatch(self.course_id)
                or not isinstance(self.topic, str) or not self.topic.strip()
                or type(self.count) is not int or not 1 <= self.count <= maximum
                or self.difficulty not in ("easy", "medium", "hard", "mixed")
                or not isinstance(self.sources, tuple) or not self.sources
                or any(not isinstance(source, SyntheticBenchmarkSource)
                       or source.course_id != self.course_id
                       or source.status != "ACTIVE" for source in self.sources)
                or len({source.source_id for source in self.sources}) != len(self.sources)
                or sum(len(source.content) for source in self.sources) > 200000):
            raise ValueError("invalid benchmark fixture")
        object.__setattr__(self, "topic", self.topic.strip())

    def context_text(self) -> str:
        return "\n\n".join(
            f"[{source.source_id}]\n{source.content}" for source in self.sources
        )

    def source_metadata(self) -> List[Dict[str, str]]:
        return [source.metadata() for source in self.sources]


@dataclass(frozen=True)
class BenchmarkTarget:
    """A provider/model instance plus optional public token prices in USD."""

    provider: Any
    input_cost_per_million: Optional[float] = None
    output_cost_per_million: Optional[float] = None
    _report_provider: str = field(init=False, repr=False)
    _report_model: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.provider is None:
            raise ValueError("invalid benchmark target")
        for value in (self.input_cost_per_million, self.output_cost_per_million):
            if value is not None and _optional_nonnegative(value) is None:
                raise ValueError("invalid benchmark target")
        try:
            raw_provider = getattr(self.provider, "provider", None)
            raw_model = getattr(self.provider, "model", None)
            identity = _TRUSTED_TARGET_IDENTITIES.get((raw_provider, raw_model))
        except Exception:
            identity = None
        if identity is None:
            raise ValueError("unsupported benchmark target") from None
        object.__setattr__(self, "_report_provider", identity[0])
        object.__setattr__(self, "_report_model", identity[1])


class _RecordingProvider:
    def __init__(self, provider: Any, report_provider: str, report_model: str):
        self._provider = provider
        self.provider = report_provider
        self.model = report_model
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
        recording = _RecordingProvider(
            target.provider, target._report_provider, target._report_model)
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
                    retrieved_context=fixture.context_text(),
                    source_metadata=fixture.source_metadata(),
                    client_facing=False,
                    temperature=0,
                )
            else:
                await FlashcardService(orchestrator).generate_grounded_flashcards(
                    topic=fixture.topic,
                    count=fixture.count,
                    difficulty=fixture.difficulty,
                    retrieved_context=fixture.context_text(),
                    source_metadata=fixture.source_metadata(),
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
        usage = self._usage(result)
        first_token = _optional_nonnegative(
            getattr(result, "first_token_latency_ms", None) if result is not None else None
        )
        return {
            "provider": target._report_provider,
            "model": target._report_model,
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
        try:
            validated_sources = tuple(SyntheticBenchmarkSource(
                course_id=source.course_id,
                source_id=source.source_id,
                content=source.content,
                version=source.version,
                status=source.status,
                content_sha256=source.content_sha256,
            ) for source in fixture.sources)
            fixture = BenchmarkFixture(
                task=fixture.task,
                course_id=fixture.course_id,
                topic=fixture.topic,
                count=fixture.count,
                difficulty=fixture.difficulty,
                sources=validated_sources,
            )
        except Exception:
            raise ValueError("invalid benchmark fixture") from None
        if not isinstance(targets, Sequence) or isinstance(targets, (str, bytes)) or not targets:
            raise ValueError("invalid benchmark targets")
        if any(not isinstance(target, BenchmarkTarget) for target in targets):
            raise ValueError("invalid benchmark targets")
        try:
            targets = tuple(BenchmarkTarget(
                target.provider,
                target.input_cost_per_million,
                target.output_cost_per_million,
            ) for target in targets)
        except Exception:
            raise ValueError("invalid benchmark targets") from None
        results: List[Dict[str, Any]] = []
        for target in targets:
            results.append(await self._run_target(fixture, target))
        return {
            "fixture": {
                "task": fixture.task,
                "course_id": fixture.course_id,
                "topic": fixture.topic,
                "count": fixture.count,
                "difficulty": fixture.difficulty,
            },
            "results": results,
        }
