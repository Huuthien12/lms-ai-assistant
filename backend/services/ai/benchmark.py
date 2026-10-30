from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.services.ai.grounded_chat import PreparedGroundedPrompt
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.provider_base import LLMProvider, LLMResult
from backend.services.ai.quality import displayed_answer, evaluate_answer


@dataclass(frozen=True)
class BenchmarkTarget:
    config: ModelConfig
    provider: LLMProvider


@dataclass(frozen=True)
class BenchmarkRecord:
    question_id: str
    model: str
    provider: str
    prompt_version: str
    document_version: tuple[str, ...]
    retrieval_config: dict[str, Any]
    chunk_ids: tuple[str, ...]
    latency: float
    token_usage: dict[str, int]
    estimated_cost: float | None
    raw_response: str
    displayed_answer: str
    evaluation_result: dict[str, Any]
    status: str
    error_code: str | None
    quality_status: str
    display_action: str
    provider_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("provider_metadata", None)
        return data


def _estimated_cost(config: ModelConfig, usage: dict[str, int]) -> float | None:
    if config.input_cost_per_million is None or config.output_cost_per_million is None:
        return None
    return round((usage.get("prompt_tokens", 0) * config.input_cost_per_million
                  + usage.get("completion_tokens", 0) * config.output_cost_per_million) / 1_000_000, 8)


class BenchmarkRunner:
    async def run(self, question_id: str, prepared: PreparedGroundedPrompt,
                  targets: list[BenchmarkTarget]) -> list[BenchmarkRecord]:
        records = []
        for target in targets:
            if target.config.is_cloud and not target.config.allow_cloud_document_content:
                result = LLMResult("error", target.config.provider, target.config.model, "", 0,
                                   error_code="CLOUD_CONTENT_DISABLED")
            else:
                result = await target.provider.generate(
                    prepared.prompt, prepared.system_prompt,
                    temperature=target.config.temperature, max_tokens=target.config.max_tokens,
                )
            raw = result.content if result.status == "success" else ""
            evaluation = evaluate_answer(result.status, raw, len(prepared.sources))
            records.append(BenchmarkRecord(
                question_id=question_id, model=target.config.model,
                provider=target.config.provider, prompt_version=prepared.prompt_version,
                document_version=prepared.document_versions,
                retrieval_config=dict(prepared.retrieval_config), chunk_ids=prepared.chunk_ids,
                latency=result.latency_ms, token_usage=dict(result.usage or {}),
                estimated_cost=_estimated_cost(target.config, result.usage or {}),
                raw_response=raw, displayed_answer=displayed_answer(result.status, raw, evaluation),
                evaluation_result=evaluation, status=result.status, error_code=result.error_code,
                quality_status=evaluation["quality_status"], display_action=evaluation["display_action"],
                provider_metadata=_safe_provider_metadata(result.metadata),
            ))
        return records


_SAFE_PROVIDER_METADATA = {
    "content_type", "content_length", "finish_reason", "native_finish_reason",
    "prompt_tokens", "completion_tokens", "reasoning_tokens", "reasoning_present",
    "reasoning_length", "http_status", "provider_response_id",
}


def _safe_provider_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value for key, value in metadata.items()
        if key in _SAFE_PROVIDER_METADATA
        and (isinstance(value, (str, int, float, bool)) or value is None)
    }
