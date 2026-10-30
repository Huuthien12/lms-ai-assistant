import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchmark.semantic_review import ReviewValidationError, validate_rows, weighted_kappa
from benchmark import generate_semantic_review_report


def manifest():
    return {"blind_ids": ["B001", "B002"], "record_hashes": {"B001": "a" * 64, "B002": "b" * 64}}


def row(blind_id, digest, state="COMPLETE"):
    complete = state == "COMPLETE"
    return {
        "blind_id": blind_id, "input_record_sha256": digest, "rubric_version": "semantic-review-v1",
        "correctness": 2 if complete else None, "relevance": 1 if complete else None,
        "clarity": 2 if complete else None, "completeness": 1 if complete else None,
        "total_8": 6 if complete else None,
        "rationale_by_criterion": {field: "linked to reviewed input" for field in ("correctness", "relevance", "clarity", "completeness")} if complete else {},
        "reference_answer_coverage": "partial" if complete else None,
        "identified_factual_errors": "none observed" if complete else None,
        "refusal_classification": "no" if complete else None,
        "evidence_verification_status": "UNVERIFIABLE",
        "reviewer_identity": "AI_CODEX", "review_method": "record-by-record semantic review",
        "review_status": state,
    }


class SemanticReviewTests(unittest.TestCase):
    def test_complete_rows_require_hashes_scores_and_per_criterion_rationale(self):
        rows = [row("B001", "a" * 64), row("B002", "b" * 64)]
        self.assertEqual("COMPLETE", validate_rows(rows, manifest(), "AI_CODEX"))
        rows[0]["rationale_by_criterion"].pop("clarity")
        with self.assertRaisesRegex(ReviewValidationError, "rationale"):
            validate_rows(rows, manifest(), "AI_CODEX")

    def test_pending_cannot_smuggle_quality_score_and_hash_mismatch_fails(self):
        rows = [row("B001", "a" * 64, "PENDING"), row("B002", "b" * 64, "PENDING")]
        self.assertEqual("PENDING", validate_rows(rows, manifest(), "AI_CODEX"))
        rows[0]["correctness"] = 1
        with self.assertRaisesRegex(ReviewValidationError, "may not contain"):
            validate_rows(rows, manifest(), "AI_CODEX")
        rows[0]["correctness"] = None
        rows[0]["input_record_sha256"] = hashlib.sha256(b"wrong").hexdigest()
        with self.assertRaisesRegex(ReviewValidationError, "mismatch"):
            validate_rows(rows, manifest(), "AI_CODEX")

    def test_weighted_kappa_is_ordinal_and_handles_no_variation(self):
        self.assertEqual(1.0, weighted_kappa([0, 1, 2], [0, 1, 2]))
        self.assertIsNone(weighted_kappa([2, 2], [2, 2]))

    def test_finalizer_requires_complete_reviews_then_forms_question_level_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = ["B001", "B002"]
            hashes = {blind_id: ("a" if blind_id == "B001" else "b") * 64 for blind_id in ids}
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps({"blind_ids": ids, "record_hashes": hashes, "manifest_hash": "locked"}), encoding="utf-8")
            a_rows = [row(blind_id, hashes[blind_id]) for blind_id in ids]
            b_rows = [{**item, "reviewer_identity": "AI_CHATGPT"} for item in a_rows]
            for name, payload in (("a.jsonl", a_rows), ("b.jsonl", b_rows)):
                (root / name).write_text("".join(json.dumps(item) + "\n" for item in payload), encoding="utf-8")
            (root / "key.jsonl").write_text("\n".join(json.dumps({"blind_id": blind_id, "run_id": "r", "question_id": "q", "provider": "p", "model": "m", "condition": condition}) for blind_id, condition in zip(ids, ("no-rag", "rag"))) + "\n", encoding="utf-8")
            output = root / "report.md"
            argv = ["generate", "--scores-a", str(root / "a.jsonl"), "--scores-b", str(root / "b.jsonl"), "--manifest", str(manifest_path), "--blind-key", str(root / "key.jsonl"), "--output", str(output), "--locked-by", "coordinator", "--unlock-key"]
            with patch.object(sys, "argv", argv):
                self.assertEqual(0, generate_semantic_review_report.main())
            self.assertIn("n=1", output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
