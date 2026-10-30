from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from backend.services.ai.benchmark import BenchmarkRunner, BenchmarkTarget
from backend.services.ai.deeptutor_provider import DeepTutorProvider
from backend.services.ai.grounded_chat import GroundedChatRequest, GroundedChatService, RetrievedContextItem
from backend.services.ai.model_config import ModelConfig
from deeptutor_integration.auth_contracts import AuthContractError, CourseAction
from deeptutor_integration.config import DeepTutorConfig
from deeptutor_integration.contracts import AuthorizedCourseScope
from deeptutor_integration.errors import DeepTutorError
from deeptutor_integration.moodle_trust import MoodleTrustBoundary
from deeptutor_integration.service import DeepTutorService
from deeptutor_integration.verified_publication import VerifiedPublicationService


@dataclass(frozen=True)
class BenchmarkQuestion:
    question_id: str
    question: str
    reference_answer: str
    reference_sources: tuple[dict[str, Any], ...] = ()


class CLIQueryAccess:
    """Live Moodle authorization for a non-HTTP benchmark process."""

    def __init__(self, boundary: MoodleTrustBoundary, token: str):
        self.boundary, self._token = boundary, token

    def scope(self, selector: int | str) -> AuthorizedCourseScope:
        context = self.boundary.authorize(self._token, selector, CourseAction.QUERY_COURSE)
        binding, scope = context.binding, context.scope
        owner_ref = sha256((binding.moodle_namespace + "\0" + str(binding.moodle_user_id)).encode()).hexdigest()
        result = AuthorizedCourseScope(scope.moodle_course_id, scope.canonical_course_key, scope.kb_id,
                                       owner_ref, scope.moodle_namespace)
        if result.canonical_scope != scope:
            raise ValueError("Moodle authorization returned an invalid course scope")
        return result

    def reauthorize(self, scope: AuthorizedCourseScope) -> AuthorizedCourseScope:
        current = self.scope(scope.moodle_course_id)
        if current != scope:
            raise PermissionError("Moodle course authorization changed")
        return current


def load_questions(path: Path) -> list[BenchmarkQuestion]:
    questions: list[BenchmarkQuestion] = []
    seen: set[str] = set()
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on input line {line_number}") from error
            if not isinstance(row, dict):
                raise ValueError(f"Input line {line_number} must be an object")
            required = {name: row.get(name) for name in ("question_id", "question", "reference_answer")}
            if any(not isinstance(value, str) or not value.strip() for value in required.values()):
                raise ValueError(f"Input line {line_number} has invalid required fields")
            question_id = required["question_id"].strip()
            if question_id in seen:
                raise ValueError(f"Duplicate question_id: {question_id}")
            sources = row.get("reference_sources", [])
            if not isinstance(sources, list) or any(not isinstance(source, dict) for source in sources):
                raise ValueError(f"Input line {line_number} has invalid reference_sources")
            seen.add(question_id)
            questions.append(BenchmarkQuestion(question_id, required["question"].strip(),
                                                required["reference_answer"].strip(), tuple(sources)))
    if not questions:
        raise ValueError("Input JSONL contains no questions")
    return questions


def _record_key(row: dict[str, Any]) -> tuple[str, str, str]:
    values = tuple(row.get(name) for name in ("question_id", "provider", "model"))
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError("Existing output contains an invalid benchmark record")
    return values  # type: ignore[return-value]


def load_completed(path: Path) -> set[tuple[str, str, str]]:
    completed: set[tuple[str, str, str]] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                key = _record_key(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid existing output line {line_number}") from error
            if key in completed:
                raise ValueError(f"Duplicate existing benchmark result: {key}")
            completed.add(key)
    return completed


def _contexts(context: Any) -> list[RetrievedContextItem]:
    return [RetrievedContextItem(
        text=chunk.content, source_id=chunk.source_ref, title=chunk.filename, score=chunk.score,
        metadata={"page": chunk.page, "chunk_id": chunk.chunk_id,
                  "document_version_id": chunk.document_version_id},
    ) for chunk in context.chunks]


def _target_config(config: ModelConfig) -> dict[str, Any]:
    return {"temperature": config.temperature, "max_tokens": config.max_tokens,
            "timeout_seconds": config.timeout_seconds,
            "cloud_document_content_enabled": config.allow_cloud_document_content}


def _retrieval_sources(prepared: Any, context: Any) -> list[dict[str, Any]]:
    chunks = {chunk.source_ref: chunk for chunk in context.chunks}
    sources = []
    for source in prepared.sources:
        item = dict(source)
        chunk = chunks.get(source.get("source_id"))
        if chunk is not None:
            item.update({"document_id": chunk.document_id,
                         "document_version_id": chunk.document_version_id,
                         "chunk_id": chunk.chunk_id,
                         "source_content_hash": chunk.content_sha256})
        sources.append(item)
    return sources


async def run_questions(questions: list[BenchmarkQuestion], output: Path, scope: AuthorizedCourseScope,
                        access: Any, publications: Any, targets: list[BenchmarkTarget], top_k: int,
                        resume: bool = False, runner: BenchmarkRunner | None = None) -> int:
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if output.exists() and output.stat().st_size and not resume:
        raise FileExistsError("Output already exists; use --resume or choose another path")
    completed = load_completed(output) if resume else set()
    output.parent.mkdir(parents=True, exist_ok=True)
    chat = GroundedChatService(object(), top_k=top_k)  # prepare() does not call the orchestrator.
    runner = runner or BenchmarkRunner()
    written = 0
    with output.open("a", encoding="utf-8", newline="\n") as stream:
        for question in questions:
            pending = [target for target in targets
                       if (question.question_id, target.config.provider, target.config.model) not in completed]
            if not pending:
                continue
            access.reauthorize(scope)
            with publications.context(scope, question.question) as context:
                publications.revalidate(context)
                prepared = chat.prepare(GroundedChatRequest(
                    query=question.question, course_id=scope.course_key, kb_name=scope.kb_name,
                    contexts=_contexts(context)))
                if prepared is None:
                    raise ValueError(f"No usable verified chunks for question {question.question_id}")
                records = await runner.run(question.question_id, prepared, pending)
                access.reauthorize(scope)
                for record, target in zip(records, pending, strict=True):
                    row = record.to_dict()
                    row.update({
                        "question": question.question,
                        "reference_answer": question.reference_answer,
                        "reference_sources": list(question.reference_sources),
                        "retrieval_context_id": context.context_id,
                        "sources": _retrieval_sources(prepared, context),
                        "generation_config": _target_config(target.config),
                    })
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    completed.add(_record_key(row))
                    written += 1
    return written


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark LLMs on one Moodle-verified retrieval snapshot")
    parser.add_argument("--input", type=Path, required=True, help="Question set in JSONL format")
    parser.add_argument("--output", type=Path, required=True, help="Benchmark results JSONL")
    parser.add_argument("--course", required=True, help="Authorized Moodle course id or shortname")
    parser.add_argument("--ollama-model", action="append", default=[], help="Repeat for each local model")
    parser.add_argument("--cloud-model", action="append", default=[], metavar="PROVIDER:MODEL",
                        help="Cloud target (openai, gemini, anthropic, groq, openrouter); requires explicit opt-in")
    parser.add_argument("--allow-cloud-document-content", action="store_true")
    parser.add_argument("--moodle-token-env", default="MOODLE_PERSONAL_TOKEN",
                        help="Environment variable containing the Moodle token")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--resume", action="store_true")
    return parser


def _models(args: argparse.Namespace, config: DeepTutorConfig) -> list[BenchmarkTarget]:
    specs: list[tuple[str, str]] = [("ollama", model) for model in args.ollama_model]
    for value in args.cloud_model:
        provider, separator, model = value.partition(":")
        if not separator or provider not in {"openai", "gemini", "anthropic", "groq", "openrouter"} or not model:
            raise ValueError(f"Invalid cloud model: {value}")
        specs.append((provider, model))
    if not specs:
        raise ValueError("At least one --ollama-model or --cloud-model is required")
    if args.cloud_model and not args.allow_cloud_document_content:
        raise ValueError("Cloud models require --allow-cloud-document-content")
    if len(set(specs)) != len(specs):
        raise ValueError("Duplicate provider/model target")
    key_names = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
                 "anthropic": "ANTHROPIC_API_KEY", "groq": "GROQ_API_KEY",
                 "openrouter": "OPENROUTER_API_KEY"}
    base_urls = {"groq": "https://api.groq.com/openai/v1",
                 "openrouter": "https://openrouter.ai/api/v1"}
    targets = []
    for provider, model in specs:
        model_config = ModelConfig(
            provider, model, temperature=args.temperature, max_tokens=args.max_tokens,
            timeout_seconds=args.timeout, api_key_env=key_names.get(provider),
            base_url=base_urls.get(provider),
            allow_cloud_document_content=args.allow_cloud_document_content,
        )
        targets.append(BenchmarkTarget(model_config, DeepTutorProvider(model_config, config.deeptutor_dir)))
    return targets


async def _main(args: argparse.Namespace) -> int:
    token = os.getenv(args.moodle_token_env, "").strip()
    if not token:
        raise ValueError(f"Moodle token environment variable is not set: {args.moodle_token_env}")
    base_url = os.getenv("MOODLE_BASE_URL", "").strip()
    if not base_url:
        raise ValueError("MOODLE_BASE_URL is not set")
    config = DeepTutorConfig.from_env()
    service = DeepTutorService(config)
    boundary = MoodleTrustBoundary(base_url, course_kb_resolver=service.kb_name)
    access = CLIQueryAccess(boundary, token)
    selector: int | str = int(args.course) if args.course.isdecimal() else args.course
    scope = access.scope(selector)
    written = await run_questions(load_questions(args.input), args.output, scope, access,
                                  VerifiedPublicationService(config), _models(args, config),
                                  args.top_k, args.resume)
    print(json.dumps({"written": written, "output": str(args.output)}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = _parser()
    try:
        return asyncio.run(_main(parser.parse_args()))
    except AuthContractError as error:
        parser.error(error.public_message)
        return 2
    except DeepTutorError as error:
        parser.error(error.message)
        return 2
    except (FileNotFoundError, FileExistsError, PermissionError, ValueError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
