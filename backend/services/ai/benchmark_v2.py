from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, ContextManager

from backend.services.ai.benchmark import BenchmarkRecord, BenchmarkRunner, BenchmarkTarget
from backend.services.ai.benchmark_cli import (
    CLIQueryAccess,
    _contexts,
    _retrieval_sources,
    _target_config,
)
from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.grounded_chat import (
    GroundedChatRequest,
    GroundedChatService,
    PreparedGroundedPrompt,
    RetrievedContextItem,
)
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.provider_base import LLMProvider, LLMResult
from backend.services.ai.quality import evaluate_answer
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_trust import MoodleTrustBoundary
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.verified_publication import VerifiedPublicationService


CONDITIONS = ("no-rag", "rag", "rag-strict", "rag-flexible")
VERIFIED_STATUS = "VERIFIED_ACTIVE"
REAL_RUN_ENV = "BENCHMARK_V2_ALLOW_REAL"
FIVE_MODELS = (
    ("ollama", "qwen2.5:3b"),
    ("ollama", "llama3.2:3b"),
    ("gemini", "gemini-3.5-flash-lite"),
    ("groq", "qwen/qwen3.8-27b"),
    ("openrouter", "liquid/lfm-2.5-2.6b:free"),
)
NO_RAG_SYSTEM_PROMPT = (
    "Trả lời ngắn gọn, rõ ràng bằng tiếng Việt. Nếu không chắc hoặc không đủ thông tin, "
    "hãy nêu rõ giới hạn và không suy đoán."
)


@dataclass(frozen=True)
class BenchmarkQuestionV2:
    question_id: str
    course_id: str
    question: str
    reference_answer: str
    reference_answer_status: str
    question_type: str
    reference_sources: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PromptSnapshot:
    prepared: PreparedGroundedPrompt
    context_id: str | None
    sources: tuple[dict[str, Any], ...]
    retrieval_latency_ms: float
    evidence_snapshot_hash: str | None = None
    reauthorize: Callable[[], None] | None = field(default=None, repr=False, compare=False)
    revalidate: Callable[[], None] | None = field(default=None, repr=False, compare=False)


SnapshotFactory = Callable[[BenchmarkQuestionV2], ContextManager[PromptSnapshot]]
RequestEventWriter = Callable[[str, BenchmarkQuestionV2, BenchmarkTarget,
                               PreparedGroundedPrompt, BenchmarkRecord | None, str | None], None]


class BenchmarkAuthorizationError(Exception):
    pass


class BenchmarkSnapshotStaleError(Exception):
    pass


class BenchmarkValidationUnavailableError(Exception):
    pass


def load_questions_v2(path: Path) -> list[BenchmarkQuestionV2]:
    questions: list[BenchmarkQuestionV2] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on input line {line_number}") from error
            required = ("question_id", "course_id", "question", "reference_answer",
                        "reference_answer_status", "question_type")
            if not isinstance(row, dict) or any(
                    not isinstance(row.get(name), str) or not row[name].strip() for name in required):
                raise ValueError(f"Input line {line_number} has invalid required fields")
            question_id = row["question_id"].strip()
            if question_id in seen:
                raise ValueError(f"Duplicate question_id: {question_id}")
            sources = row.get("reference_sources")
            if not isinstance(sources, list) or not sources or any(not isinstance(x, dict) for x in sources):
                raise ValueError(f"Input line {line_number} has invalid reference_sources")
            seen.add(question_id)
            questions.append(BenchmarkQuestionV2(
                question_id, row["course_id"].strip(), row["question"].strip(),
                row["reference_answer"].strip(), row["reference_answer_status"].strip(),
                row["question_type"].strip(), tuple(sources),
            ))
    if not questions:
        raise ValueError("Input JSONL contains no questions")
    return questions


def prompt_hash(prepared: PreparedGroundedPrompt) -> str:
    payload = json.dumps(
        {"prompt": prepared.prompt, "system_prompt": prepared.system_prompt},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def snapshot_hash(snapshot: PromptSnapshot) -> str:
    payload = json.dumps({
        "prompt_hash": prompt_hash(snapshot.prepared),
        "chunk_ids": snapshot.prepared.chunk_ids,
        "document_versions": snapshot.prepared.document_versions,
        "retrieval_config": snapshot.prepared.retrieval_config,
        "sources": snapshot.sources,
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def prepare_no_rag(question: BenchmarkQuestionV2) -> PromptSnapshot:
    prepared = PreparedGroundedPrompt(
        prompt=question.question,
        system_prompt=NO_RAG_SYSTEM_PROMPT,
        sources=(), chunk_ids=(), document_versions=(),
        retrieval_config={"mode": "none", "top_k": 0, "selected_chunks": 0},
        prompt_version="benchmark-v2-no-rag-v1",
    )
    return PromptSnapshot(prepared, None, (), 0.0)


def mock_rag_snapshot(question: BenchmarkQuestionV2, top_k: int) -> PromptSnapshot:
    contexts = []
    for index, source in enumerate(question.reference_sources, 1):
        contexts.append(RetrievedContextItem(
            text=str(source.get("evidence_excerpt") or "Verified fixture evidence"),
            source_id=f"fixture:{question.question_id}:{index}",
            title=str(source.get("document_name") or "fixture-document"), score=1.0,
            metadata={"chunk_id": f"fixture-{question.question_id}-{index}",
                      "document_id": source.get("document_id"),
                      "document_version_id": source.get("document_version_id")},
        ))
    prepared = GroundedChatService(object(), top_k=top_k).prepare(GroundedChatRequest(
        query=question.question, course_id=question.course_id, contexts=contexts,
    ))
    if prepared is None:
        raise ValueError(f"No usable fixture chunks for {question.question_id}")
    sources = tuple({
        **dict(item),
        "document_id": source.get("document_id"),
        "document_version_id": source.get("document_version_id"),
        "source_content_hash": sha256(str(source.get("evidence_excerpt") or "").encode("utf-8")).hexdigest(),
    } for item, source in zip(prepared.sources, question.reference_sources, strict=True))
    return PromptSnapshot(prepared, f"mock:{question.question_id}", sources, 0.0)


def _record_key(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    names = ("run_id", "condition", "question_id", "provider", "model")
    values = tuple(row.get(name) for name in names)
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Existing output contains an invalid benchmark v2 record")
    return values  # type: ignore[return-value]


def _completed(path: Path) -> set[tuple[str, str, str, str, str]]:
    keys: set[tuple[str, str, str, str, str]] = set()
    if not path.exists():
        return keys
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                key = _record_key(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid existing output line {line_number}") from error
            if key in keys:
                raise ValueError(f"Duplicate existing benchmark v2 result: {key}")
            keys.add(key)
    return keys


def _existing_provenance(path: Path) -> dict[tuple[str, str, str], tuple[str, tuple[str, ...], tuple[str, ...]]]:
    groups: dict[tuple[str, str, str], tuple[str, tuple[str, ...], tuple[str, ...]]] = {}
    if not path.exists():
        return groups
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = tuple(row[name] for name in ("run_id", "condition", "question_id"))
                value = (row["prompt_hash"], tuple(row.get("document_version_ids", ())),
                         tuple(row.get("chunk_ids", ())))
            except (json.JSONDecodeError, KeyError, TypeError) as error:
                raise ValueError(f"Invalid existing output provenance on line {line_number}") from error
            if key in groups and groups[key] != value:
                raise ValueError(f"Existing output mixes snapshot provenance: {key}")
            groups[key] = value
    return groups


def _existing_generation_configs(path: Path) -> dict[tuple[str, str, str, str, str], dict[str, Any]]:
    configs: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    if not path.exists():
        return configs
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                key = _record_key(row)
                config = row["generation_config"]
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid existing generation configuration on line {line_number}") from error
            if not isinstance(config, dict):
                raise ValueError(f"Invalid existing generation configuration on line {line_number}")
            configs[key] = config
    return configs


def _error_record(question_id: str, target: BenchmarkTarget, prepared: PreparedGroundedPrompt,
                  error_code: str) -> BenchmarkRecord:
    evaluation = evaluate_answer("error", "", len(prepared.sources))
    return BenchmarkRecord(
        question_id=question_id, model=target.config.model, provider=target.config.provider,
        prompt_version=prepared.prompt_version, document_version=prepared.document_versions,
        retrieval_config=dict(prepared.retrieval_config), chunk_ids=prepared.chunk_ids,
        latency=0.0, token_usage={}, estimated_cost=None, raw_response="", displayed_answer="",
        evaluation_result=evaluation, status="error", error_code=error_code,
        quality_status=evaluation["quality_status"], display_action=evaluation["display_action"],
    )


def _validate_snapshot(snapshot: PromptSnapshot, expected_hash: str) -> None:
    if snapshot_hash(snapshot) != expected_hash:
        raise BenchmarkSnapshotStaleError()
    if snapshot.reauthorize is not None:
        snapshot.reauthorize()
    if snapshot.revalidate is not None:
        snapshot.revalidate()
    if snapshot_hash(snapshot) != expected_hash:
        raise BenchmarkSnapshotStaleError()


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payload = "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


async def run_benchmark_v2(
    questions: list[BenchmarkQuestionV2], output: Path, run_id: str, condition: str,
    targets: list[BenchmarkTarget], snapshots: SnapshotFactory, *, resume: bool = False,
    runner: BenchmarkRunner | None = None, execution_mode: str = "mock",
    request_event_writer: RequestEventWriter | None = None,
) -> int:
    if condition not in CONDITIONS or execution_mode not in {"mock", "real"} or not run_id.strip() or not targets:
        raise ValueError("Invalid benchmark v2 run configuration")
    if output.exists() and output.stat().st_size and not resume:
        raise FileExistsError("Output already exists; use --resume or choose another run id")
    completed = _completed(output) if resume else set()
    existing_provenance = _existing_provenance(output) if resume else {}
    existing_generation_configs = _existing_generation_configs(output) if resume else {}
    output.parent.mkdir(parents=True, exist_ok=True)
    runner = runner or BenchmarkRunner()
    written = 0
    group_output = output.with_name(output.stem + ".groups.jsonl")
    for question_index, question in enumerate(questions):
        offset = question_index % len(targets)
        ordered_targets = targets[offset:] + targets[:offset]
        for target in ordered_targets:
            key = (run_id, condition, question.question_id, target.config.provider, target.config.model)
            if key in completed and existing_generation_configs.get(key) != _target_config(target.config):
                raise ValueError(f"Resume generation configuration changed for {question.question_id}")
        pending = [target for target in ordered_targets if (
            run_id, condition, question.question_id, target.config.provider, target.config.model
        ) not in completed]
        if not pending:
            continue
        with snapshots(question) as snapshot:
            digest = prompt_hash(snapshot.prepared)
            integrity = snapshot_hash(snapshot)
        provenance_key = (run_id, condition, question.question_id)
        provenance = (digest, snapshot.prepared.document_versions, snapshot.prepared.chunk_ids)
        if provenance_key in existing_provenance and existing_provenance[provenance_key] != provenance:
            raise ValueError(f"Resume snapshot provenance changed for {question.question_id}")
        group_id = sha256(f"{run_id}\0{condition}\0{question.question_id}\0{digest}".encode()).hexdigest()
        outcomes: list[tuple[BenchmarkRecord, BenchmarkTarget, bool]] = []
        group_status = "valid"
        group_error_code: str | None = None
        for index, target in enumerate(pending):
            try:
                _validate_snapshot(snapshot, integrity)
            except BenchmarkAuthorizationError:
                group_status, group_error_code = "authorization_failed", "AUTHORIZATION_FAILED"
            except BenchmarkSnapshotStaleError:
                group_status, group_error_code = "snapshot_stale", "SNAPSHOT_STALE"
            except BenchmarkValidationUnavailableError:
                group_status, group_error_code = "validation_unavailable", "SNAPSHOT_VALIDATION_UNAVAILABLE"
            if group_error_code is not None:
                outcomes.extend((_error_record(question.question_id, item, snapshot.prepared,
                                               group_error_code), item, False)
                                for item in pending[index:])
                break
            try:
                if request_event_writer is not None:
                    request_event_writer("request_started", question, target, snapshot.prepared, None, None)
                record = (await runner.run(question.question_id, snapshot.prepared, [target]))[0]
                outcomes.append((record, target, True))
                if request_event_writer is not None:
                    request_event_writer("request_completed", question, target, snapshot.prepared,
                                         record, record.error_code)
            except KeyboardInterrupt:
                if request_event_writer is not None:
                    request_event_writer("request_interrupted", question, target, snapshot.prepared,
                                         None, "INTERRUPTED")
                raise
            except Exception:
                group_status, group_error_code = "generation_exception", "UNEXPECTED_PROVIDER_EXCEPTION"
                record = _error_record(question.question_id, target, snapshot.prepared, group_error_code)
                outcomes.append((record, target, True))
                if request_event_writer is not None:
                    request_event_writer("request_completed", question, target, snapshot.prepared,
                                         record, group_error_code)
                outcomes.extend((_error_record(question.question_id, item, snapshot.prepared,
                                               "BATCH_ABORTED"), item, False)
                                for item in pending[index + 1:])
                break
        if group_status == "valid":
            try:
                _validate_snapshot(snapshot, integrity)
            except BenchmarkAuthorizationError:
                group_status, group_error_code = "authorization_failed", "AUTHORIZATION_FAILED"
            except BenchmarkSnapshotStaleError:
                group_status, group_error_code = "snapshot_stale", "SNAPSHOT_STALE"
            except BenchmarkValidationUnavailableError:
                group_status, group_error_code = "validation_unavailable", "SNAPSHOT_VALIDATION_UNAVAILABLE"
        generated_at = datetime.now(timezone.utc).isoformat()
        group_eligible = (execution_mode == "real" and group_status == "valid"
                          and question.reference_answer_status == VERIFIED_STATUS)
        rows = []
        for record, target, provider_called in outcomes:
            row = record.to_dict()
            row.update({
                "schema_version": "benchmark-result/v2",
                "execution_mode": execution_mode,
                "run_id": run_id,
                "condition": condition,
                "course_id": question.course_id,
                "question": question.question,
                "question_type": question.question_type,
                "reference_answer_status": question.reference_answer_status,
                "official_accuracy_eligible": group_eligible,
                "evaluation_group": ("main_verified" if question.reference_answer_status == VERIFIED_STATUS
                                     else "insufficient_evidence_manual_review"),
                "comparison_group_id": group_id,
                "comparison_group_status": group_status,
                "comparison_group_error_code": group_error_code,
                "provider_called": provider_called,
                "prompt_hash": digest,
                "snapshot_hash": integrity,
                "evidence_snapshot_hash": snapshot.evidence_snapshot_hash,
                "retrieval_context_id": snapshot.context_id,
                "document_version_ids": list(snapshot.prepared.document_versions),
                "sources": list(snapshot.sources),
                "retrieval_latency_ms": snapshot.retrieval_latency_ms,
                "provider_latency_ms": row["latency"],
                "provider_metadata": dict(record.provider_metadata),
                "latency_scope": "provider_generation_only",
                "generation_config": _target_config(target.config),
                "cloud_document_content_sent": (condition != "no-rag" and target.config.is_cloud
                                                and provider_called and not isinstance(target.provider, MockProvider)),
                "generated_at_utc": generated_at,
                "evaluation_result_kind": "format_and_citation_heuristic_not_semantic_accuracy",
                "manual_score_schema": {"common_score": "0-8", "rag_evidence_score": (
                    "0-4" if condition == "rag" else None)},
            })
            rows.append(row)
        _append_jsonl(output, rows)
        _append_jsonl(group_output, [{
            "schema_version": "benchmark-comparison-group/v1",
            "execution_mode": execution_mode,
            "run_id": run_id, "condition": condition, "course_id": question.course_id,
            "question_id": question.question_id, "comparison_group_id": group_id,
            "status": group_status, "error_code": group_error_code,
            "official_accuracy_eligible": group_eligible, "prompt_hash": digest,
            "snapshot_hash": integrity, "evidence_snapshot_hash": snapshot.evidence_snapshot_hash,
            "document_version_ids": list(snapshot.prepared.document_versions),
            "chunk_ids": list(snapshot.prepared.chunk_ids), "target_count": len(pending),
            "provider_calls": sum(called for _, _, called in outcomes), "validated_at_utc": generated_at,
        }])
        for row in rows:
            completed.add(_record_key(row))
        existing_provenance[provenance_key] = provenance
        written += len(rows)
    return written


class MockProvider(LLMProvider):
    def __init__(self, provider: str, model: str):
        self.provider, self.model = provider, model

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> LLMResult:
        return LLMResult("success", self.provider, self.model,
                         "MOCK_RESPONSE (không có API request)", 0.0,
                         usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})

    async def health_check(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "status": "available"}


def _parse_model(value: str) -> tuple[str, str]:
    provider, separator, model = value.partition(":")
    if not separator or provider not in {"ollama", "openai", "gemini", "anthropic", "groq", "openrouter"} or not model:
        raise ValueError(f"Invalid model target: {value}")
    return provider, model


def _targets(specs: list[tuple[str, str]], args: argparse.Namespace, config: DeepTutorConfig) -> list[BenchmarkTarget]:
    if not specs or len(specs) != len(set(specs)):
        raise ValueError("At least one unique model target is required")
    cloud = any(provider != "ollama" for provider, _ in specs)
    if args.execute_real and cloud and not args.allow_cloud:
        raise ValueError("Cloud models require --allow-cloud")
    if args.execute_real and args.condition != "no-rag" and cloud and not args.allow_cloud_document_content:
        raise ValueError("RAG cloud models require --allow-cloud-document-content")
    keys = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY",
            "openrouter": "OPENROUTER_API_KEY"}
    bases = {"groq": "https://api.groq.com/openai/v1",
             "openrouter": "https://openrouter.ai/api/v1"}
    targets = []
    for provider, model in specs:
        max_tokens = (args.diagnostic_openrouter_max_tokens
                      if provider == "openrouter" and args.diagnostic_openrouter_max_tokens is not None
                      else 1024)
        cfg = ModelConfig(
            provider, model, temperature=0.1, max_tokens=max_tokens, timeout_seconds=180,
            api_key_env=keys.get(provider), base_url=bases.get(provider),
            allow_cloud_document_content=(not args.execute_real or provider == "ollama" or args.condition == "no-rag"
                                          or args.allow_cloud_document_content),
        )
        adapter: LLMProvider = (DeepTutorProvider(cfg, config.deeptutor_dir) if args.execute_real
                                else MockProvider(provider, model))
        targets.append(BenchmarkTarget(cfg, adapter))
    return targets


def _capture_rag_snapshot(question: BenchmarkQuestionV2, scope: Any, access: Any,
                          publications: Any, top_k: int) -> PromptSnapshot:
    document_ids = {str(source.get("document_id") or "") for source in question.reference_sources}
    expected_versions = {str(source.get("document_version_id") or "") for source in question.reference_sources}
    if len(document_ids) != 1 or "" in document_ids or "" in expected_versions:
        raise ValueError(f"Question {question.question_id} does not pin one valid document/version scope")
    access.reauthorize(scope)
    started = time.monotonic()
    with publications.context(scope, question.question, document_id=next(iter(document_ids))) as context:
        publications.revalidate(context)
        retrieval_ms = (time.monotonic() - started) * 1000
        prepared = GroundedChatService(object(), top_k=top_k).prepare(GroundedChatRequest(
            query=question.question, course_id=scope.course_key, kb_name=scope.kb_name,
            contexts=_contexts(context),
        ))
        if prepared is None or set(prepared.document_versions) != expected_versions:
            raise ValueError(f"Verified retrieval version mismatch for {question.question_id}")
        captured_context = context
        captured_sources = tuple(dict(item) for item in _retrieval_sources(prepared, context))

    def reauthorize() -> None:
        try:
            access.reauthorize(scope)
        except Exception:
            raise BenchmarkAuthorizationError() from None

    def revalidate() -> None:
        try:
            with publications.ledger._locked():
                publications.revalidate(captured_context)
        except DeepTutorError as error:
            if error.code == "inactive_context":
                raise BenchmarkSnapshotStaleError() from None
            raise BenchmarkValidationUnavailableError() from None
        except Exception:
            raise BenchmarkValidationUnavailableError() from None

    return PromptSnapshot(prepared, captured_context.context_id, captured_sources, retrieval_ms,
                          reauthorize=reauthorize, revalidate=revalidate)


def _real_access(args: argparse.Namespace, config: DeepTutorConfig) -> tuple[CLIQueryAccess, Any]:
    token = os.getenv(args.moodle_token_env, "").strip()
    base_url = os.getenv("MOODLE_BASE_URL", "").strip()
    if not token or not base_url:
        raise ValueError("Real run requires MOODLE_BASE_URL and the configured Moodle token environment variable")
    service = DeepTutorService(config)
    access = CLIQueryAccess(MoodleTrustBoundary(base_url, course_kb_resolver=service.kb_name), token)
    scope = access.scope(args.course)
    if scope.course_key.casefold() != args.course.casefold():
        raise ValueError("Authorized Moodle course does not match --course")
    return access, scope


def _real_no_rag_factory(args: argparse.Namespace, config: DeepTutorConfig) -> SnapshotFactory:
    access, scope = _real_access(args, config)

    @contextmanager
    def factory(question: BenchmarkQuestionV2):
        snapshot = prepare_no_rag(question)

        def reauthorize() -> None:
            try:
                access.reauthorize(scope)
            except Exception:
                raise BenchmarkAuthorizationError() from None

        yield replace(snapshot, reauthorize=reauthorize)
    return factory


def _real_rag_factory(args: argparse.Namespace, config: DeepTutorConfig) -> SnapshotFactory:
    access, scope = _real_access(args, config)
    publications = VerifiedPublicationService(config)

    @contextmanager
    def factory(question: BenchmarkQuestionV2):
        yield _capture_rag_snapshot(question, scope, access, publications, args.top_k)
    return factory


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reproducible 30-question RAG/No-RAG benchmark v2")
    parser.add_argument("--input", type=Path, default=Path("benchmark/questions-30-v2.jsonl"))
    parser.add_argument("--output-root", type=Path, default=Path("benchmark/runs-v2"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--course", choices=("INT1339", "INT2001"), required=True)
    parser.add_argument("--condition", choices=CONDITIONS, required=True)
    parser.add_argument("--model", action="append", default=[], metavar="PROVIDER:MODEL")
    parser.add_argument("--five-models", action="store_true")
    parser.add_argument("--question-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--verified-only", action="store_true",
                        help="Run only questions with reference_answer_status=VERIFIED_ACTIVE")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--diagnostic-openrouter-max-tokens", type=int, metavar="N",
                        help="RAG diagnostic only: override OpenRouter output budget above baseline 1024")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--execute-real", action="store_true",
                        help=f"Enable providers/retrieval; also requires {REAL_RUN_ENV}=YES")
    parser.add_argument("--allow-cloud", action="store_true")
    parser.add_argument("--allow-cloud-document-content", action="store_true")
    parser.add_argument("--moodle-token-env", default="MOODLE_PERSONAL_TOKEN")
    return parser


def _validate_diagnostic_budget(args: argparse.Namespace, specs: list[tuple[str, str]]) -> None:
    value = args.diagnostic_openrouter_max_tokens
    if value is None:
        return
    if value <= 1024:
        raise ValueError("--diagnostic-openrouter-max-tokens must be greater than baseline 1024")
    if args.condition not in {"rag", "rag-strict"} or len(specs) != 1 or specs[0][0] != "openrouter":
        raise ValueError("--diagnostic-openrouter-max-tokens requires one OpenRouter RAG target")


def _select_questions(args: argparse.Namespace, questions: list[BenchmarkQuestionV2]) -> list[BenchmarkQuestionV2]:
    selected = [question for question in questions if question.course_id == args.course]
    if args.verified_only:
        selected = [question for question in selected if question.reference_answer_status == VERIFIED_STATUS]
    if args.question_id:
        wanted = set(args.question_id)
        selected = [question for question in selected if question.question_id in wanted]
        missing = wanted - {question.question_id for question in selected}
        if missing:
            raise ValueError(f"Unknown or excluded question ids for {args.course}: {sorted(missing)}")
    if args.limit is not None:
        selected = selected[:args.limit]
    if not selected:
        raise ValueError("No questions selected")
    return selected


async def _main(args: argparse.Namespace) -> int:
    if args.execute_real and os.getenv(REAL_RUN_ENV) != "YES":
        raise ValueError(f"Real execution requires {REAL_RUN_ENV}=YES and --execute-real")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}", args.run_id):
        raise ValueError("--run-id must be 1-80 safe filename characters")
    if args.limit is not None and args.limit <= 0:
        raise ValueError("--limit must be positive")
    if args.top_k <= 0:
        raise ValueError("--top-k must be positive")
    specs = list(FIVE_MODELS if args.five_models else ()) + [_parse_model(x) for x in args.model]
    _validate_diagnostic_budget(args, specs)
    config = DeepTutorConfig.from_env()
    targets = _targets(specs, args, config)
    questions = _select_questions(args, load_questions_v2(args.input))
    output = args.output_root / args.run_id / args.course / f"{args.condition}.jsonl"
    if args.execute_real and args.condition != "no-rag":
        snapshots = _real_rag_factory(args, config)
    elif args.execute_real:
        snapshots = _real_no_rag_factory(args, config)
    elif args.condition != "no-rag":
        snapshots = lambda question: nullcontext(mock_rag_snapshot(question, args.top_k))
    else:
        snapshots = lambda question: nullcontext(prepare_no_rag(question))
    written = await run_benchmark_v2(questions, output, args.run_id, args.condition,
                                     targets, snapshots, resume=args.resume,
                                     execution_mode="real" if args.execute_real else "mock")
    print(json.dumps({"mode": "real" if args.execute_real else "mock", "written": written,
                      "output": str(output)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = _parser()
    try:
        return asyncio.run(_main(parser.parse_args()))
    except (FileNotFoundError, FileExistsError, PermissionError, ValueError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
