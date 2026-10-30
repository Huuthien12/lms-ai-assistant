from pathlib import Path
import sys

from backend.services.ai.quiz_service import OutputSchemaError


sys.path.insert(0, str(Path(__file__).parents[1] / "lms-dlu-demo"))
from learning_generation import LearningGenerationService


def test_semantic_grounding_failure_never_triggers_schema_retry():
    error=OutputSchemaError("INVALID_QUIZ_SCHEMA: grounding", category="grounding", field="evidence",
                            diagnostics={"grounding_failure_reason":"empty_cloze"})
    assert not LearningGenerationService._may_schema_retry("quiz", error, 10)


def test_non_grounding_schema_failure_has_one_bounded_retry():
    error=OutputSchemaError("INVALID_QUIZ_SCHEMA: json", category="json_parse", field="root")
    assert LearningGenerationService._may_schema_retry("quiz", error, 10)
    assert not LearningGenerationService._may_schema_retry("quiz", error, 0)
