import ast
from copy import deepcopy
import inspect

import pytest

from backend.services.ai.mastery_service import MasteryService


SCOPE = {"student_id": "student-1", "course_id": "course-1", "topic": "Python"}


def quiz(correct):
    return {**SCOPE, "type": "quiz", "correct": correct}


def card(rating):
    return {**SCOPE, "type": "flashcard", "rating": rating}


def calculate(evidence, **scope_changes):
    return MasteryService().calculate_mastery(
        **{**SCOPE, **scope_changes}, evidence=evidence)


def test_no_evidence():
    assert calculate([]) == {
        **SCOPE, "mastery_score": None, "level": None, "confidence": "LOW",
        "evidence_count": 0,
        "components": {"quiz_accuracy": None, "quiz_evidence_count": 0,
                       "flashcard_score": None, "flashcard_evidence_count": 0},
    }


@pytest.mark.parametrize("answers,score,level", [
    ([True, True], 100.0, "MASTERED"),
    ([True, False], 50.0, "DEVELOPING"),
    ([False, False], 0.0, "WEAK"),
    ([True, False, False], 33.33, "WEAK"),
])
def test_quiz_only(answers, score, level):
    result = calculate([quiz(answer) for answer in answers])
    assert result["mastery_score"] == score
    assert result["level"] == level
    assert result["components"]["quiz_accuracy"] == sum(answers) / len(answers)
    assert result["components"]["flashcard_score"] is None


@pytest.mark.parametrize("rating,score", [
    ("AGAIN", 0.0), ("HARD", 40.0), ("GOOD", 75.0), ("EASY", 100.0),
])
def test_rating_mapping(rating, score):
    result = calculate([card(rating)])
    assert result["mastery_score"] == score
    assert result["components"]["quiz_accuracy"] is None


def test_flashcard_mean():
    result = calculate([card(r) for r in ("AGAIN", "HARD", "GOOD", "EASY")])
    assert result["mastery_score"] == 53.75
    assert result["components"]["flashcard_score"] == 0.5375


@pytest.mark.parametrize("evidence,score", [
    ([quiz(True), quiz(False), card("GOOD")], 55.0),
    ([quiz(True)] + [card("AGAIN") for _ in range(9)], 80.0),
    ([quiz(False)] + [card("EASY") for _ in range(9)], 20.0),
])
def test_mixed_weights_are_per_component(evidence, score):
    result = calculate(evidence)
    assert result["mastery_score"] == score
    assert result["evidence_count"] == len(evidence)
    assert result["components"]["quiz_evidence_count"] == sum(
        item["type"] == "quiz" for item in evidence)
    assert result["components"]["flashcard_evidence_count"] == sum(
        item["type"] == "flashcard" for item in evidence)


@pytest.mark.parametrize("score,level", [
    (49.99, "WEAK"), (50, "DEVELOPING"), (69.99, "DEVELOPING"),
    (70, "GOOD"), (84.99, "GOOD"), (85, "MASTERED"),
])
def test_level_boundaries(score, level):
    assert MasteryService._level(score) == level


@pytest.mark.parametrize("count,confidence", [
    (0, "LOW"), (4, "LOW"), (5, "MEDIUM"), (14, "MEDIUM"),
    (15, "HIGH"), (20, "HIGH"),
])
def test_confidence(count, confidence):
    result = calculate([quiz(True) for _ in range(count)])
    assert result["confidence"] == confidence
    assert result["evidence_count"] == count


@pytest.mark.parametrize("field", list(SCOPE))
@pytest.mark.parametrize("value", ["other", " Python", None, 1])
def test_cross_scope_rejected(field, value):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate([{**quiz(True), field: value}])


@pytest.mark.parametrize("field", list(SCOPE))
@pytest.mark.parametrize("value", ["", "  ", None, 1])
def test_invalid_requested_scope(field, value):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate([], **{field: value})


@pytest.mark.parametrize("correct", [0, 1, "true", "false", None, [], {}])
def test_invalid_quiz_correct(correct):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate([quiz(correct)])


@pytest.mark.parametrize("rating", ["good", " GOOD", "UNKNOWN", None, 1, [], {}])
def test_invalid_rating(rating):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate([card(rating)])


@pytest.mark.parametrize("kind", ["chat", "material", "material_open", "interaction", None, []])
def test_unsupported_evidence(kind):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate([{**SCOPE, "type": kind}])


@pytest.mark.parametrize("evidence", [
    None, {}, (), "payload", [None], [[]], ["payload"], [{}],
    [{**SCOPE, "type": "quiz"}], [{**SCOPE, "type": "flashcard"}],
    [{"type": "quiz", "correct": True}],
])
def test_invalid_structure(evidence):
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        calculate(evidence)


def test_safe_errors():
    with pytest.raises(ValueError) as error:
        calculate([{**quiz(True), "student_id": "SECRET_UNRELATED_PAYLOAD"}])
    assert str(error.value).startswith("INVALID_MASTERY_INPUT")
    assert "SECRET_UNRELATED_PAYLOAD" not in str(error.value)


def test_inputs_preserved_and_repeated_results_identical():
    evidence = [quiz(True), quiz(False), card("HARD")]
    evidence[0]["extra"] = {"nested": [1, 2]}
    before = deepcopy(evidence)
    first = calculate(evidence)
    assert calculate(evidence) == first
    assert evidence == before


def test_no_llm_provider_or_persistence_dependency():
    import backend.services.ai.mastery_service as module

    tree = ast.parse(inspect.getsource(module))
    imports = [node for node in ast.walk(tree)
               if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(node, ast.ImportFrom) and node.module == "typing"
               for node in imports)
    assert not any(isinstance(node, ast.AsyncFunctionDef) for node in ast.walk(tree))
