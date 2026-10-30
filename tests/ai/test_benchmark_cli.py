import json
from argparse import Namespace
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services.ai.benchmark import BenchmarkTarget
from backend.services.ai.benchmark_cli import _models, load_questions, run_questions
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.provider_base import LLMResult
from deeptutor_integration.contracts import AuthorizedCourseScope
from deeptutor_integration.config import DeepTutorConfig


class FakeAccess:
    def __init__(self):
        self.calls = 0

    def reauthorize(self, scope):
        self.calls += 1
        return scope


class FakePublications:
    def __init__(self):
        self.retrievals = 0
        self.context_ids = []

    @contextmanager
    def context(self, scope, question):
        self.retrievals += 1
        context = SimpleNamespace(context_id=f"snapshot-{self.retrievals}", chunks=[SimpleNamespace(
            content="Verified evidence", source_ref="source-1", filename="chapter.pdf", score=0.9,
            page=1, document_id="document-1", chunk_id="chunk-1", document_version_id="version-1")])
        self.context_ids.append(context.context_id)
        yield context

    def revalidate(self, context):
        return True


def target(model, result):
    provider = AsyncMock()
    provider.generate = AsyncMock(return_value=result)
    return BenchmarkTarget(ModelConfig("ollama", model, temperature=0, max_tokens=100), provider)


def question():
    return SimpleNamespace(question_id="q-1", question="What?", reference_answer="Reference",
                           reference_sources=({"document_id": "doc-1"},))


@pytest.mark.asyncio
async def test_cli_retrieves_once_and_shares_exact_prompt(tmp_path):
    first_raw = "Phép nhân có thể được ghi là 乘以 [Nguồn 1]."
    first = target("model-a", LLMResult("success", "ollama", "model-a", first_raw, 4))
    second = target("model-b", LLMResult("success", "ollama", "model-b", "B [Nguồn 1]", 5))
    publications, access = FakePublications(), FakeAccess()
    output = tmp_path / "results.jsonl"

    written = await run_questions([question()], output,
        AuthorizedCourseScope(2, "INT1339", "kb", "owner", "moodle:test"), access,
        publications, [first, second], 3)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert written == 2 and publications.retrievals == 1
    assert first.provider.generate.await_args.args == second.provider.generate.await_args.args
    assert {row["retrieval_context_id"] for row in rows} == {"snapshot-1"}
    assert all(row["chunk_ids"] == ["chunk-1"] and row["reference_answer"] == "Reference" for row in rows)
    assert all(row["sources"][0]["document_id"] == "document-1" for row in rows)
    assert all("api_key" not in json.dumps(row).lower() for row in rows)
    assert rows[0]["raw_response"] == rows[0]["displayed_answer"] == first_raw
    assert rows[0]["quality_status"] == "warning" and rows[0]["display_action"] == "raw"
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")


@pytest.mark.asyncio
async def test_cli_records_model_error_and_resume_writes_only_missing_target(tmp_path):
    output = tmp_path / "results.jsonl"
    output.write_text(json.dumps({"question_id": "q-1", "provider": "ollama", "model": "done"}) + "\n",
                      encoding="utf-8")
    done = target("done", LLMResult("success", "ollama", "done", "unused", 1))
    failed = target("failed", LLMResult("error", "ollama", "failed", "SECRET", 8,
                                        error_code="TIMEOUT_OR_NETWORK_ERROR"))
    publications = FakePublications()

    written = await run_questions([question()], output,
        AuthorizedCourseScope(2, "INT1339", "kb", "owner", "moodle:test"), FakeAccess(),
        publications, [done, failed], 3, resume=True)

    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert written == 1 and publications.retrievals == 1
    done.provider.generate.assert_not_awaited()
    failed.provider.generate.assert_awaited_once()
    assert rows[-1]["status"] == "error" and rows[-1]["error_code"] == "TIMEOUT_OR_NETWORK_ERROR"
    assert rows[-1]["raw_response"] == "" and "SECRET" not in output.read_text(encoding="utf-8")
    assert len({(row["question_id"], row["provider"], row["model"]) for row in rows}) == len(rows)


def test_question_jsonl_validation_and_optional_sources(tmp_path):
    path = tmp_path / "questions.jsonl"
    path.write_text(json.dumps({"question_id": "q-1", "question": "Tiếng Việt?", "reference_answer": "Nhân 乘以",
                                "reference_sources": [{"document_id": "doc", "page": 2}]}, ensure_ascii=False) + "\n",
                    encoding="utf-8-sig")
    loaded = load_questions(path)
    assert loaded[0].reference_sources == ({"document_id": "doc", "page": 2},)
    assert loaded[0].question == "Tiếng Việt?" and loaded[0].reference_answer == "Nhân 乘以"

    path.write_text('\n'.join([
        json.dumps({"question_id": "same", "question": "Q", "reference_answer": "A"}),
        json.dumps({"question_id": "same", "question": "Q2", "reference_answer": "A2"}),
    ]), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate question_id"):
        load_questions(path)


def test_cli_cloud_target_requires_explicit_document_opt_in(tmp_path):
    args = Namespace(ollama_model=[], cloud_model=["openai:test-model"],
                     allow_cloud_document_content=False, temperature=0.1,
                     max_tokens=100, timeout=10)
    config = DeepTutorConfig(tmp_path, tmp_path / "DeepTutor", tmp_path / "deeptutor",
                             tmp_path / "runtime")
    with pytest.raises(ValueError, match="--allow-cloud-document-content"):
        _models(args, config)
