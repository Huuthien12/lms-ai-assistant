from typing import Any, Dict, List


class GradingService:
    """Deterministic MCQ grading; no retrieval, provider, or persistence dependency.

    IDs must be non-blank strings and are compared exactly, without normalization.
    Missing answers and explicit None selections are unanswered and incorrect.
    Answer keys in results are intended for post-submission use only.
    """

    @staticmethod
    def _require_id(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("INVALID_GRADING_INPUT: expected a non-blank id")
        return value

    def grade(
        self, questions: List[Dict[str, Any]], answers: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        if not isinstance(questions, list) or not questions:
            raise ValueError("INVALID_GRADING_INPUT: quiz must be non-empty")
        if not isinstance(answers, list):
            raise ValueError("INVALID_GRADING_INPUT: answers must be a list")

        quiz = {}
        for question in questions:
            if not isinstance(question, dict):
                raise ValueError("INVALID_GRADING_INPUT: invalid question")
            question_id = self._require_id(question.get("question_id"))
            if question_id in quiz:
                raise ValueError("INVALID_GRADING_INPUT: duplicate quiz question id")
            if question.get("type") != "mcq":
                raise ValueError("INVALID_GRADING_INPUT: only mcq is supported")
            correct_id = self._require_id(question.get("correct_option_id"))
            options = question.get("options")
            if not isinstance(options, list) or len(options) < 2:
                raise ValueError("INVALID_GRADING_INPUT: mcq requires at least two options")
            option_ids = set()
            for option in options:
                if not isinstance(option, dict):
                    raise ValueError("INVALID_GRADING_INPUT: invalid option")
                option_id = self._require_id(option.get("id"))
                if option_id in option_ids:
                    raise ValueError("INVALID_GRADING_INPUT: duplicate option id")
                option_ids.add(option_id)
            if correct_id not in option_ids:
                raise ValueError("INVALID_GRADING_INPUT: answer key not in options")
            quiz[question_id] = (correct_id, option_ids)

        selections = {}
        for answer in answers:
            if not isinstance(answer, dict):
                raise ValueError("INVALID_GRADING_INPUT: invalid answer")
            question_id = self._require_id(answer.get("question_id"))
            if question_id not in quiz:
                raise ValueError("INVALID_GRADING_INPUT: unknown answer question id")
            if question_id in selections:
                raise ValueError("INVALID_GRADING_INPUT: duplicate student answer")
            if "selected_option_id" not in answer:
                raise ValueError("INVALID_GRADING_INPUT: selected_option_id is required")
            selected_id = answer["selected_option_id"]
            if selected_id is not None:
                self._require_id(selected_id)
                if selected_id not in quiz[question_id][1]:
                    raise ValueError("INVALID_GRADING_INPUT: selected option not in options")
            selections[question_id] = selected_id

        results = []
        for question_id, (correct_id, _) in quiz.items():
            selected_id = selections.get(question_id)
            results.append({
                "question_id": question_id,
                "correct": selected_id == correct_id,
                "selected_option_id": selected_id,
                "correct_option_id": correct_id,
            })
        correct_count = sum(result["correct"] for result in results)
        total_questions = len(results)
        return {
            "score_percent": round(correct_count / total_questions * 100, 2),
            "correct_count": correct_count,
            "total_questions": total_questions,
            "results": results,
        }
