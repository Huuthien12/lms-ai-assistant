import ast
from copy import deepcopy
import inspect
from unittest.mock import AsyncMock, patch

import pytest

from backend.services.ai.grading_service import GradingService


@pytest.fixture
def questions():
    return [
        {"question_id": question_id, "type": "mcq", "correct_option_id": "A",
         "options": [{"id": "A", "text": "First"}, {"id": "B", "text": "Second"}]}
        for question_id in ("Q3", "Q1", "Q2")
    ]


def answers_for(questions, selections):
    return [{"question_id": q["question_id"], "selected_option_id": selected}
            for q, selected in zip(questions, selections)]


@pytest.mark.parametrize("selections,count,score", [
    (["A", "A", "A"], 3, 100.0),
    (["B", "B", "B"], 0, 0.0),
    (["A", "B", "A"], 2, 66.67),
    (["A", "B", "B"], 1, 33.33),
])
def test_exact_grading_and_rounding(questions, selections, count, score):
    result = GradingService().grade(questions, answers_for(questions, selections))
    assert result == {
        "score_percent": score, "correct_count": count, "total_questions": 3,
        "results": [
            {"question_id": q["question_id"], "correct": selected == "A",
             "selected_option_id": selected}
            for q, selected in zip(questions, selections)
        ],
    }


def test_omitted_and_explicit_none_are_incorrect(questions):
    answers = answers_for(questions, ["A", None])
    result = GradingService().grade(questions, answers)
    assert result["score_percent"] == 33.33
    assert result["correct_count"] == 1
    assert all(not row["correct"] and row["selected_option_id"] is None
               for row in result["results"][1:])
    assert GradingService().grade(questions, [])["correct_count"] == 0


def test_result_order_matches_quiz_not_answers(questions):
    answers = answers_for(questions, ["A", "B", "A"])[::-1]
    before = deepcopy((questions, answers))
    result = GradingService().grade(questions, answers)
    assert [row["question_id"] for row in result["results"]] == ["Q3", "Q1", "Q2"]
    assert [row["correct"] for row in result["results"]] == [True, False, True]
    assert (questions, answers) == before


@pytest.mark.parametrize("answers", [
    [{"question_id": "UNKNOWN", "selected_option_id": "A"}],
    [{"question_id": "Q3", "selected_option_id": None},
     {"question_id": "Q3", "selected_option_id": "A"}],
    [{"question_id": "Q3", "selected_option_id": "C"}],
    [{"question_id": "Q3", "selected_option_id": "a"}],
    [{"question_id": "Q3", "selected_option_id": " A "}],
    [{"question_id": "Q3", "selected_option_id": ""}],
    [{"question_id": "Q3", "selected_option_id": []}],
    [{"question_id": "Q3"}],
    [{"question_id": " ", "selected_option_id": "A"}],
    [None], None, {},
])
def test_invalid_student_answers_rejected(questions, answers):
    with pytest.raises(ValueError, match="^INVALID_GRADING_INPUT"):
        GradingService().grade(questions, answers)


def test_duplicate_quiz_question_id_rejected(questions):
    questions[1]["question_id"] = questions[0]["question_id"]
    with pytest.raises(ValueError, match="INVALID_GRADING_INPUT"):
        GradingService().grade(questions, [])


@pytest.mark.parametrize("mutation", [
    {"question_id": ""}, {"question_id": "  "}, {"question_id": None},
    {"question_id": []}, {"type": "tf"}, {"type": None},
    {"correct_option_id": "C"}, {"correct_option_id": ""},
    {"correct_option_id": None}, {"correct_option_id": []},
    {"options": []}, {"options": [{"id": "A"}]},
    {"options": [{"id": "A"}, {"id": "A"}]},
    {"options": [{"id": "A"}, {"id": " "}]},
    {"options": [{"id": "A"}, {"id": 1}]},
    {"options": [{"id": "A"}, None]}, {"options": None},
])
def test_invalid_quiz_schema_rejected(questions, mutation):
    questions[0].update(mutation)
    with pytest.raises(ValueError, match="^INVALID_GRADING_INPUT"):
        GradingService().grade(questions, [])


@pytest.mark.parametrize("questions", [[], None, {}, [None]])
def test_empty_or_invalid_quiz_rejected(questions):
    with pytest.raises(ValueError, match="^INVALID_GRADING_INPUT"):
        GradingService().grade(questions, [])


def test_text_and_explanation_do_not_affect_correctness(questions):
    for q in questions:
        q.update(question="B is correct", explanation="Choose B", model_output="B")
        q["options"][0]["text"] = "Wrong"
        q["options"][1]["text"] = "Correct"
    result = GradingService().grade(questions, answers_for(questions, ["B", "A", "B"]))
    assert [row["correct"] for row in result["results"]] == [False, True, False]


def test_errors_do_not_echo_payload(questions):
    secret = "secret-unrelated-payload"
    with pytest.raises(ValueError) as raised:
        GradingService().grade(questions, [{"question_id": secret, "selected_option_id": secret}])
    assert str(raised.value).startswith("INVALID_GRADING_INPUT")
    assert secret not in str(raised.value)


def test_grading_has_no_llm_dependency_or_calls(questions):
    import backend.services.ai.grading_service as module

    tree = ast.parse(inspect.getsource(module))
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(isinstance(node, ast.ImportFrom) and node.module == "typing" for node in imports)
    with patch("backend.services.ai.orchestrator.AIOrchestrator.generate", new_callable=AsyncMock) as generate:
        GradingService().grade(questions, answers_for(questions, ["A", "B", "A"]))
        generate.assert_not_called()
