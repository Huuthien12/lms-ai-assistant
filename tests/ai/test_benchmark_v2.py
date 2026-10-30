import asyncio
from contextlib import contextmanager, nullcontext
from dataclasses import replace
import json
from multiprocessing import get_context
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from backend.services.ai.benchmark import BenchmarkTarget
from backend.services.ai.benchmark_v2 import (
    FIVE_MODELS,
    MockProvider,
    BenchmarkAuthorizationError,
    BenchmarkSnapshotStaleError,
    _capture_rag_snapshot,
    _parser,
    _select_questions,
    _targets,
    _validate_diagnostic_budget,
    load_questions_v2,
    mock_rag_snapshot,
    prepare_no_rag,
    prompt_hash,
    run_benchmark_v2,
)
from backend.services.ai.model_config import ModelConfig
from backend.services.ai.provider_base import LLMProvider, LLMResult
from deeptutor_integration.moodle_ingestion_ledger import MoodleIngestionLedgerV2


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmark" / "questions-30-v2.jsonl"


def _acquire_ledger_lock(root, results):
    try:
        with MoodleIngestionLedgerV2(Path(root), lock_timeout_seconds=0.5)._locked():
            results.put("acquired")
    except Exception:
        results.put("blocked")


class CapturingProvider(LLMProvider):
    def __init__(self, model, *, fail=False):
        self.provider, self.model, self.fail = "ollama", model, fail
        self.calls = []

    async def generate(self, prompt, system_prompt=None, **kwargs):
        self.calls.append((prompt, system_prompt, kwargs))
        if self.fail:
            return LLMResult("error", self.provider, self.model, "SECRET_SHOULD_NOT_LEAK", 7,
                             error_code="TIMEOUT_OR_NETWORK_ERROR")
        return LLMResult("success", self.provider, self.model, "Câu trả lời mock", 5,
                         usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13})

    async def health_check(self):
        return {"status": "available"}


class RaisingProvider(CapturingProvider):
    async def generate(self, prompt, system_prompt=None, **kwargs):
        self.calls.append((prompt, system_prompt, kwargs))
        raise RuntimeError("private provider failure")


class LockProbeProvider(CapturingProvider):
    def __init__(self, model, ledger_root):
        super().__init__(model)
        self.ledger_root = ledger_root

    async def generate(self, prompt, system_prompt=None, **kwargs):
        process_context = get_context("spawn")
        results = process_context.Queue()
        process = process_context.Process(target=_acquire_ledger_lock,
                                          args=(self.ledger_root, results))
        process.start(); process.join(5)
        outcome = results.get(timeout=1)
        self.calls.append((prompt, system_prompt, kwargs))
        return LLMResult("error", self.provider, self.model, "", 1,
                         error_code="TIMEOUT_OR_NETWORK_ERROR" if outcome == "acquired" else "LOCK_HELD")


def target(model, provider=None):
    provider = provider or CapturingProvider(model)
    return BenchmarkTarget(ModelConfig("ollama", model, temperature=0.1,
                                       max_tokens=1024, timeout_seconds=180), provider)


class BenchmarkV2Tests(unittest.TestCase):
    def test_dataset_split_and_manual_review_are_explicit(self):
        questions = load_questions_v2(DATASET)
        self.assertEqual(30, len(questions))
        self.assertEqual({"INT1339": 15, "INT2001": 15}, {
            course: sum(q.course_id == course for q in questions)
            for course in ("INT1339", "INT2001")
        })
        manual = [q.question_id for q in questions if q.reference_answer_status == "NEEDS_MANUAL_REVIEW"]
        self.assertEqual(["int1339-v2-15", "int2001-v2-15"], manual)

    def test_verified_only_selects_fourteen_per_course_before_limit_without_mutation(self):
        questions = load_questions_v2(DATASET)
        original_ids = [question.question_id for question in questions]
        parser = _parser()
        for course, expected in (("INT1339", ["int1339-v2-01", "int1339-v2-02"]),
                                 ("INT2001", ["int2001-v2-01", "int2001-v2-02"])):
            default = parser.parse_args(["--run-id", "run", "--course", course,
                                         "--condition", "rag", "--model", "ollama:qwen2.5:3b"])
            verified = parser.parse_args(["--run-id", "run", "--course", course,
                                          "--condition", "rag", "--model", "ollama:qwen2.5:3b",
                                          "--verified-only"])
            limited = parser.parse_args(["--run-id", "run", "--course", course,
                                         "--condition", "rag", "--model", "ollama:qwen2.5:3b",
                                         "--verified-only", "--limit", "2"])
            self.assertEqual(15, len(_select_questions(default, questions)))
            selected = _select_questions(verified, questions)
            self.assertEqual(14, len(selected))
            self.assertTrue(all(question.reference_answer_status == "VERIFIED_ACTIVE" for question in selected))
            self.assertEqual(expected, [question.question_id for question in _select_questions(limited, questions)])
            self.assertEqual(len({question.question_id for question in selected}), len(selected))
            excluded = parser.parse_args(["--run-id", "run", "--course", course,
                                          "--condition", "rag", "--model", "ollama:qwen2.5:3b",
                                          "--verified-only", "--question-id", f"{course.casefold()}-v2-15"])
            with self.assertRaises(ValueError):
                _select_questions(excluded, questions)
        self.assertEqual(original_ids, [question.question_id for question in questions])

    def test_no_rag_prompt_contains_only_instruction_and_question(self):
        question = load_questions_v2(DATASET)[0]
        snapshot = prepare_no_rag(question)
        serialized = snapshot.prepared.prompt + snapshot.prepared.system_prompt
        self.assertEqual(question.question, snapshot.prepared.prompt)
        self.assertNotIn(question.reference_answer, serialized)
        self.assertNotIn("evidence_excerpt", serialized)
        self.assertNotIn("document_id", serialized)
        self.assertNotIn("citation", serialized.casefold())
        self.assertEqual((), snapshot.prepared.sources)
        self.assertEqual(prompt_hash(snapshot.prepared), prompt_hash(prepare_no_rag(question).prepared))

    def test_mock_rag_uses_only_the_question_course_and_pinned_version(self):
        questions = load_questions_v2(DATASET)
        question = questions[0]
        snapshot = mock_rag_snapshot(question, 3)
        source = question.reference_sources[0]
        other_course_documents = {item["document_id"] for candidate in questions
                                  if candidate.course_id != question.course_id
                                  for item in candidate.reference_sources}
        self.assertEqual((source["document_version_id"],), snapshot.prepared.document_versions)
        self.assertEqual(source["document_id"], snapshot.sources[0]["document_id"])
        self.assertTrue({item["document_id"] for item in snapshot.sources}.isdisjoint(other_course_documents))
        self.assertNotIn(question.reference_answer, snapshot.prepared.prompt)

    def test_models_share_snapshot_hash_and_provider_error_is_retained(self):
        question = load_questions_v2(DATASET)[0]
        first, second = CapturingProvider("first", fail=True), CapturingProvider("second")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run" / "INT1339" / "rag.jsonl"
            snapshot = mock_rag_snapshot(question, 3)
            written = asyncio.run(run_benchmark_v2(
                [question], output, "run-1", "rag", [target("first", first), target("second", second)],
                lambda _: nullcontext(snapshot),
            ))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(2, written)
        self.assertEqual(first.calls[0][:2], second.calls[0][:2])
        self.assertEqual({prompt_hash(snapshot.prepared)}, {row["prompt_hash"] for row in rows})
        self.assertEqual("error", rows[0]["status"])
        self.assertEqual("TIMEOUT_OR_NETWORK_ERROR", rows[0]["error_code"])
        self.assertEqual("", rows[0]["raw_response"])
        self.assertEqual("success", rows[1]["status"])
        self.assertNotIn("SECRET", json.dumps(rows))
        self.assertTrue(all(row["latency_scope"] == "provider_generation_only" for row in rows))

    def test_provider_diagnostics_are_written_to_v2_artifact(self):
        question = load_questions_v2(DATASET)[0]
        provider = CapturingProvider("diagnostic")
        provider.generate = AsyncMock(return_value=LLMResult(
            "error", "ollama", "diagnostic", "", 7, error_code="EMPTY_RESPONSE",
            metadata={"content_type": "str", "content_length": 0, "finish_reason": "length",
                      "reasoning_tokens": 1024, "reasoning_present": True,
                      "reasoning_length": 2048, "http_status": 200,
                      "provider_response_id": "gen-123", "raw_response": "SECRET"}))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run" / "INT1339" / "rag.jsonl"
            asyncio.run(run_benchmark_v2(
                [question], output, "diagnostic-run", "rag", [target("diagnostic", provider)],
                lambda _: nullcontext(mock_rag_snapshot(question, 3)),
            ))
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("EMPTY_RESPONSE", row["error_code"])
        self.assertEqual({"content_type": "str", "content_length": 0,
                          "finish_reason": "length", "reasoning_tokens": 1024,
                          "reasoning_present": True, "reasoning_length": 2048,
                          "http_status": 200, "provider_response_id": "gen-123"},
                         row["provider_metadata"])
        self.assertNotIn("SECRET", json.dumps(row))

    def test_resume_does_not_duplicate_and_existing_output_requires_resume(self):
        question = load_questions_v2(DATASET)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run" / "INT1339" / "no-rag.jsonl"
            factory = lambda q: nullcontext(prepare_no_rag(q))
            asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag", [target("one")], factory))
            with self.assertRaises(FileExistsError):
                asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag", [target("one")], factory))
            written = asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag",
                                                  [target("one"), target("two")], factory, resume=True))
            rows = output.read_text(encoding="utf-8").splitlines()
        self.assertEqual(1, written)
        self.assertEqual(2, len(rows))
        self.assertEqual(2, len({(json.loads(row)["question_id"], json.loads(row)["model"])
                                 for row in rows}))

    def test_manual_review_is_excluded_from_official_accuracy(self):
        question = next(q for q in load_questions_v2(DATASET)
                        if q.reference_answer_status == "NEEDS_MANUAL_REVIEW")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "manual.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag", [target("one")],
                                        lambda q: nullcontext(prepare_no_rag(q))))
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertFalse(row["official_accuracy_eligible"])
        self.assertEqual("insufficient_evidence_manual_review", row["evaluation_group"])
        self.assertNotIn("reference_answer", row)
        self.assertIsNone(row["manual_score_schema"]["rag_evidence_score"])

    def test_mock_output_is_never_official_but_valid_real_output_is(self):
        question = load_questions_v2(DATASET)[0]
        with tempfile.TemporaryDirectory() as directory:
            mock_output, real_output = Path(directory) / "mock.jsonl", Path(directory) / "real.jsonl"
            factory = lambda q: nullcontext(prepare_no_rag(q))
            asyncio.run(run_benchmark_v2([question], mock_output, "mock-run", "no-rag",
                                         [target("one")], factory))
            asyncio.run(run_benchmark_v2([question], real_output, "real-run", "no-rag",
                                         [target("one")], factory, execution_mode="real"))
            mock_row = json.loads(mock_output.read_text(encoding="utf-8"))
            real_row = json.loads(real_output.read_text(encoding="utf-8"))
        self.assertFalse(mock_row["official_accuracy_eligible"])
        self.assertTrue(real_row["official_accuracy_eligible"])

    def test_five_model_set_is_the_historical_set(self):
        self.assertEqual(5, len(FIVE_MODELS))
        self.assertEqual(5, len(set(FIVE_MODELS)))
        self.assertIn(("ollama", "qwen2.5:3b"), FIVE_MODELS)
        self.assertIn(("groq", "qwen/qwen3.8-27b"), FIVE_MODELS)

    def test_openrouter_diagnostic_budget_defaults_and_overrides_only_for_rag(self):
        baseline = _parser().parse_args([
            "--run-id", "baseline", "--course", "INT1339", "--condition", "rag",
            "--model", "openrouter:liquid/lfm-2.5-2.6b:free",
        ])
        specs = [("openrouter", "liquid/lfm-2.5-2.6b:free")]
        _validate_diagnostic_budget(baseline, specs)
        config = SimpleNamespace(deeptutor_dir=Path("."))
        self.assertEqual(1024, _targets(specs, baseline, config)[0].config.max_tokens)

        diagnostic = _parser().parse_args([
            "--run-id", "diagnostic", "--course", "INT1339", "--condition", "rag",
            "--model", "openrouter:liquid/lfm-2.5-2.6b:free",
            "--diagnostic-openrouter-max-tokens", "2048",
        ])
        _validate_diagnostic_budget(diagnostic, specs)
        self.assertEqual(2048, _targets(specs, diagnostic, config)[0].config.max_tokens)

        no_rag = _parser().parse_args([
            "--run-id", "invalid", "--course", "INT1339", "--condition", "no-rag",
            "--model", "openrouter:liquid/lfm-2.5-2.6b:free",
            "--diagnostic-openrouter-max-tokens", "2048",
        ])
        with self.assertRaises(ValueError):
            _validate_diagnostic_budget(no_rag, specs)

    def test_resume_rejects_changed_generation_configuration(self):
        question = load_questions_v2(DATASET)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run" / "INT1339" / "rag.jsonl"
            factory = lambda _: nullcontext(mock_rag_snapshot(question, 3))
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag", [target("one")], factory))
            changed = BenchmarkTarget(ModelConfig("ollama", "one", temperature=0.1,
                                                   max_tokens=2048, timeout_seconds=180),
                                      CapturingProvider("one"))
            with self.assertRaisesRegex(ValueError, "generation configuration changed"):
                asyncio.run(run_benchmark_v2([question], output, "run-1", "rag", [changed],
                                             factory, resume=True))

    def test_target_order_rotates_deterministically_by_question(self):
        first = load_questions_v2(DATASET)[0]
        second = replace(first, question_id="second")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rotation.jsonl"
            asyncio.run(run_benchmark_v2(
                [first, second], output, "run-1", "no-rag",
                [target("one"), target("two"), target("three")],
                lambda q: nullcontext(prepare_no_rag(q)),
            ))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["one", "two", "three"], [row["model"] for row in rows[:3]])
        self.assertEqual(["two", "three", "one"], [row["model"] for row in rows[3:]])

    def test_snapshot_context_releases_real_process_lock_before_provider(self):
        question = load_questions_v2(DATASET)[0]
        with tempfile.TemporaryDirectory() as directory:
            ledger = MoodleIngestionLedgerV2(Path(directory))
            source = question.reference_sources[0]
            context = SimpleNamespace(context_id="context-1", chunks=(SimpleNamespace(
                content=source["evidence_excerpt"], source_ref="source-1",
                filename=source["document_name"], score=1.0, page=1,
                document_id=source["document_id"], chunk_id="chunk-1",
                document_version_id=source["document_version_id"],
            ),))

            class Publications:
                def __init__(self): self.ledger = ledger

                @contextmanager
                def context(self, *args, **kwargs):
                    with ledger._locked():
                        yield context

                def revalidate(self, value):
                    self.assert_context = value

            class Access:
                def reauthorize(self, value): return value

            publications = Publications()
            scope = SimpleNamespace(course_key=question.course_id, kb_name="kb")

            @contextmanager
            def factory(value):
                captured = _capture_rag_snapshot(value, scope, Access(), publications, 3)
                with ledger._locked():
                    pass
                yield captured

            provider = LockProbeProvider("probe", directory)
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                         [target("probe", provider)], factory))
            row = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual("TIMEOUT_OR_NETWORK_ERROR", row["error_code"])
        self.assertEqual("valid", row["comparison_group_status"])
        self.assertEqual(1, len(provider.calls))

    def test_reauthorization_failure_before_third_model_stops_remaining_calls(self):
        question = load_questions_v2(DATASET)[0]
        providers = [CapturingProvider(str(index)) for index in range(5)]
        checks = 0

        def authorize():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise BenchmarkAuthorizationError()

        snapshot = replace(mock_rag_snapshot(question, 3), reauthorize=authorize)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                         [target(str(i), p) for i, p in enumerate(providers)],
                                         lambda _: nullcontext(snapshot)))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual([1, 1, 0, 0, 0], [len(provider.calls) for provider in providers])
        self.assertEqual({"authorization_failed"}, {row["comparison_group_status"] for row in rows})
        self.assertTrue(all(not row["official_accuracy_eligible"] for row in rows))
        self.assertEqual([True, True, False, False, False], [row["provider_called"] for row in rows])

    def test_stale_before_third_model_stops_batch_and_invalidates_group(self):
        question = load_questions_v2(DATASET)[0]
        providers = [CapturingProvider(str(index)) for index in range(5)]
        checks = 0

        def validate():
            nonlocal checks
            checks += 1
            if checks == 3:
                raise BenchmarkSnapshotStaleError()

        snapshot = replace(mock_rag_snapshot(question, 3), revalidate=validate)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                         [target(str(i), p) for i, p in enumerate(providers)],
                                         lambda _: nullcontext(snapshot)))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            group = json.loads(output.with_name("results.groups.jsonl").read_text(encoding="utf-8"))
        self.assertEqual([1, 1, 0, 0, 0], [len(provider.calls) for provider in providers])
        self.assertEqual("snapshot_stale", group["status"])
        self.assertEqual(2, group["provider_calls"])
        self.assertTrue(all(not row["official_accuracy_eligible"] for row in rows))

    def test_stale_after_last_model_invalidates_all_results(self):
        question = load_questions_v2(DATASET)[0]
        checks = 0
        providers = [CapturingProvider(str(index)) for index in range(5)]

        def validate():
            nonlocal checks
            checks += 1
            if checks == 6:
                raise BenchmarkSnapshotStaleError()

        snapshot = replace(mock_rag_snapshot(question, 3), revalidate=validate)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                         [target(str(i), provider) for i, provider in enumerate(providers)],
                                         lambda _: nullcontext(snapshot)))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(all(row["status"] == "success" for row in rows))
        self.assertTrue(all(row["comparison_group_status"] == "snapshot_stale" for row in rows))
        self.assertTrue(all(not row["official_accuracy_eligible"] for row in rows))
        self.assertEqual(1, len({row["snapshot_hash"] for row in rows}))
        self.assertEqual(1, len({provider.calls[0][:2] for provider in providers}))

    def test_unexpected_provider_exception_is_recorded_and_aborts_batch(self):
        question = load_questions_v2(DATASET)[0]
        bad, remaining = RaisingProvider("bad"), CapturingProvider("remaining")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag",
                                         [target("bad", bad), target("remaining", remaining)],
                                         lambda q: nullcontext(prepare_no_rag(q))))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual("UNEXPECTED_PROVIDER_EXCEPTION", rows[0]["error_code"])
        self.assertEqual("BATCH_ABORTED", rows[1]["error_code"])
        self.assertEqual(0, len(remaining.calls))
        self.assertNotIn("private provider failure", json.dumps(rows))
        self.assertTrue(all(not row["official_accuracy_eligible"] for row in rows))

    def test_provider_429_and_503_are_records_without_fallback(self):
        question = load_questions_v2(DATASET)[0]
        providers = []
        targets = []
        for model, code in (("rate", "HTTP_429"), ("down", "HTTP_503")):
            provider = CapturingProvider(model)
            provider.generate = AsyncMock(return_value=LLMResult(
                "error", "ollama", model, "", 2, error_code=code))
            providers.append(provider); targets.append(target(model, provider))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "no-rag", targets,
                                         lambda q: nullcontext(prepare_no_rag(q))))
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["HTTP_429", "HTTP_503"], [row["error_code"] for row in rows])
        self.assertTrue(all(not row.get("fallback_used", False) for row in rows))

    def test_resume_rejects_changed_snapshot_provenance(self):
        question = load_questions_v2(DATASET)[0]
        original = mock_rag_snapshot(question, 3)
        changed_prepared = replace(original.prepared, chunk_ids=("different-chunk",))
        changed = replace(original, prepared=changed_prepared)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag", [target("one")],
                                         lambda _: nullcontext(original)))
            with self.assertRaisesRegex(ValueError, "provenance changed"):
                asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                             [target("one"), target("two")],
                                             lambda _: nullcontext(changed), resume=True))

    def test_output_failure_does_not_create_valid_group_marker(self):
        question = load_questions_v2(DATASET)[0]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            with patch("backend.services.ai.benchmark_v2._append_jsonl",
                       side_effect=OSError("private disk failure")):
                with self.assertRaises(OSError):
                    asyncio.run(run_benchmark_v2(
                        [question], output, "run-1", "no-rag", [target("one")],
                        lambda q: nullcontext(prepare_no_rag(q))))
            self.assertFalse(output.with_name("results.groups.jsonl").exists())

    def test_resume_stale_event_invalidates_prior_group_append_only(self):
        question = load_questions_v2(DATASET)[0]
        snapshot = mock_rag_snapshot(question, 3)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "results.jsonl"
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag", [target("one")],
                                         lambda _: nullcontext(snapshot)))
            def stale_validate():
                raise BenchmarkSnapshotStaleError()
            stale = replace(snapshot, revalidate=stale_validate)
            asyncio.run(run_benchmark_v2([question], output, "run-1", "rag",
                                         [target("one"), target("two")],
                                         lambda _: nullcontext(stale), resume=True))
            events = [json.loads(line) for line in output.with_name(
                "results.groups.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["valid", "snapshot_stale"], [event["status"] for event in events])
        self.assertFalse(events[-1]["official_accuracy_eligible"])
        self.assertEqual(events[0]["comparison_group_id"], events[-1]["comparison_group_id"])


if __name__ == "__main__":
    unittest.main()
