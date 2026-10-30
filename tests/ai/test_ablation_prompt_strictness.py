import json
import os
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.services.ai.ablation_prompt_strictness import (
    AblationPreflightError,
    build_strict_flexible_pair,
    create_private_run_directory,
    append_request_event,
    evidence_records,
    verify_private_acl,
    write_private_evidence_snapshot,
)
from backend.services.ai.benchmark_v2 import load_questions_v2, mock_rag_snapshot, prompt_hash
from benchmark import run_prompt_strictness_ablation as harness


ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "benchmark" / "questions-30-v2.jsonl"


class PromptStrictnessAblationTests(unittest.TestCase):
    def _args(self, course, question_ids):
        return SimpleNamespace(input=DATASET, course=course, question_id=question_ids)

    def test_target_questions_and_bc_plan_are_exactly_eight_calls(self):
        first = harness._questions(self._args("INT1339", ["int1339-v2-02"]))
        second = harness._questions(self._args("INT2001", ["int2001-v2-01"]))
        conditions = harness._conditions("rag-strict,rag-flexible")
        self.assertEqual(["int1339-v2-02"], [item.question_id for item in first])
        self.assertEqual(["int2001-v2-01"], [item.question_id for item in second])
        self.assertEqual(("rag-strict", "rag-flexible"), conditions)
        self.assertEqual(8, (len(first) + len(second)) * len(conditions) * len(harness.MODELS))

    def test_question_course_and_condition_validation_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "belong"):
            harness._questions(self._args("INT1339", ["int2001-v2-01"]))
        with self.assertRaisesRegex(ValueError, "conditions"):
            harness._conditions("rag-strict,unknown")

    def test_missing_secret_blocks_before_private_directory_creation(self):
        args = SimpleNamespace()
        with patch.dict(os.environ, {}, clear=True), patch.object(
                harness, "create_private_run_directory") as create:
            with self.assertRaises(AblationPreflightError):
                harness._preflight(args, Path(tempfile.gettempdir()) / "never-create")
        create.assert_not_called()

    def test_unapproved_acl_principal_is_rejected(self):
        path = Path("private")
        with patch("backend.services.ai.ablation_prompt_strictness._icacls",
                   return_value="private BUILTIN\\Users:(RX)\n"):
            with self.assertRaisesRegex(AblationPreflightError, "unapproved"):
                verify_private_acl(path, "ACER\\sorik", "S-1-5-21-1")

    def test_private_directory_write_failure_blocks_before_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "run"
            with patch("backend.services.ai.ablation_prompt_strictness.current_windows_identity",
                       return_value=("ACER\\sorik", "S-1-5-21-1")), \
                 patch("backend.services.ai.ablation_prompt_strictness._icacls",
                       return_value="run ACER\\sorik:(F)\n"), \
                 patch("backend.services.ai.ablation_prompt_strictness.verify_private_acl"), \
                 patch("backend.services.ai.ablation_prompt_strictness.os.open",
                       side_effect=PermissionError("no write")):
                with self.assertRaises(PermissionError):
                    create_private_run_directory(target)
            self.assertFalse((target / ".preflight-write-probe").exists())

    def test_failure_after_one_request_keeps_completed_request_events_without_evidence_text(self):
        question = load_questions_v2(DATASET)[0]
        strict, _ = build_strict_flexible_pair(mock_rag_snapshot(question, 3))
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "events.jsonl"
            common = {"run_id": "run", "question_id": question.question_id,
                      "condition": "rag-strict", "evidence_snapshot_hash": strict.evidence_snapshot_hash,
                      "prompt_hash": prompt_hash(strict.prepared)}
            append_request_event(journal, "request_started", model="first", **common)
            append_request_event(journal, "request_completed", model="first", status="success",
                                 error_code=None, **common)
            append_request_event(journal, "request_started", model="second", **common)
            append_request_event(journal, "request_completed", model="second", status="error",
                                 error_code="UNEXPECTED_PROVIDER_EXCEPTION", **common)
            events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(["request_started", "request_completed", "request_started", "request_completed"],
                         [event["event"] for event in events])
        self.assertEqual("success", events[1]["status"])
        self.assertEqual("UNEXPECTED_PROVIDER_EXCEPTION", events[-1]["error_code"])
        self.assertNotIn(evidence_records(strict)[0]["content"], json.dumps(events))

    def test_interrupt_event_is_explicit_and_contains_no_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / "events.jsonl"
            append_request_event(journal, "request_interrupted", run_id="run", question_id="question",
                                 model="model", condition="rag-strict", evidence_snapshot_hash="hash",
                                 prompt_hash="prompt")
            event = json.loads(journal.read_text(encoding="utf-8"))
        self.assertEqual("INTERRUPTED", event["status"])
        self.assertEqual("INTERRUPTED", event["error_code"])
        self.assertNotIn("content", event)

    def test_strict_and_flexible_share_verbatim_evidence_but_not_prompt(self):
        question = load_questions_v2(DATASET)[0]
        strict, flexible = build_strict_flexible_pair(mock_rag_snapshot(question, 3))
        self.assertEqual(evidence_records(strict), evidence_records(flexible))
        self.assertEqual(strict.evidence_snapshot_hash, flexible.evidence_snapshot_hash)
        self.assertEqual(strict.prepared.chunk_ids, flexible.prepared.chunk_ids)
        self.assertEqual(strict.prepared.document_versions, flexible.prepared.document_versions)
        self.assertNotEqual(prompt_hash(strict.prepared), prompt_hash(flexible.prepared))
        self.assertNotIn(question.reference_answer, strict.prepared.prompt)
        self.assertNotIn(question.reference_answer, flexible.prepared.prompt)

    def test_private_snapshot_has_auditable_fields_and_cannot_be_overwritten(self):
        question = load_questions_v2(DATASET)[0]
        strict, _ = build_strict_flexible_pair(mock_rag_snapshot(question, 3))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            write_private_evidence_snapshot(path, "diagnostic-run", question.question_id, strict)
            payload = json.loads(path.read_text(encoding="utf-8"))
            with self.assertRaises(FileExistsError):
                write_private_evidence_snapshot(path, "diagnostic-run", question.question_id, strict)
        self.assertEqual(strict.evidence_snapshot_hash, payload["evidence_snapshot_hash"])
        self.assertEqual(list(range(1, len(payload["chunks"]) + 1)),
                         [chunk["order"] for chunk in payload["chunks"]])
        self.assertTrue(all({"chunk_id", "document_version", "source_identifier",
                             "content_hash", "source_content_hash", "content"} <= chunk.keys()
                            for chunk in payload["chunks"]))
        self.assertTrue(all(chunk["document_version"] for chunk in payload["chunks"]))

    def test_missing_explicit_document_version_fails_closed(self):
        snapshot = mock_rag_snapshot(load_questions_v2(DATASET)[0], 3)
        stripped = replace(snapshot, sources=tuple({"source_id": item["source_id"]}
                                                   for item in snapshot.sources))
        with self.assertRaisesRegex(ValueError, "explicit document version"):
            build_strict_flexible_pair(stripped)

    def test_missing_verified_source_content_hash_fails_closed(self):
        snapshot = mock_rag_snapshot(load_questions_v2(DATASET)[0], 3)
        stripped = replace(snapshot, sources=tuple({key: value for key, value in item.items()
                                                    if key != "source_content_hash"}
                                                   for item in snapshot.sources))
        with self.assertRaisesRegex(ValueError, "verified source content hash"):
            build_strict_flexible_pair(stripped)

if __name__ == "__main__":
    unittest.main()
