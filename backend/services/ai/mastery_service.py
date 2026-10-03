from typing import Any, Dict, List


class MasteryService:
    """Calculate mastery from caller-supplied quiz and flashcard evidence only.

    Scope strings are compared exactly, without normalization. This service has
    no provider, retrieval, or persistence dependency and never mutates evidence.
    """

    @staticmethod
    def _level(score: float) -> str:
        if score < 50:
            return "WEAK"
        if score < 70:
            return "DEVELOPING"
        if score < 85:
            return "GOOD"
        return "MASTERED"

    def calculate_mastery(
        self, *, student_id: str, course_id: str, topic: str,
        evidence: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        scope = {"student_id": student_id, "course_id": course_id, "topic": topic}
        if any(not isinstance(value, str) or not value.strip()
               for value in scope.values()):
            raise ValueError("INVALID_MASTERY_INPUT: invalid scope")
        if not isinstance(evidence, list):
            raise ValueError("INVALID_MASTERY_INPUT: evidence must be a list")

        quiz_count = correct_count = flashcard_count = 0
        flashcard_total = 0.0
        ratings = {"AGAIN": 0.0, "HARD": 0.4, "GOOD": 0.75, "EASY": 1.0}
        for item in evidence:
            if not isinstance(item, dict):
                raise ValueError("INVALID_MASTERY_INPUT: invalid evidence item")
            if any(not isinstance(item.get(key), str) or item[key] != value
                   for key, value in scope.items()):
                raise ValueError("INVALID_MASTERY_INPUT: evidence scope mismatch")
            if item.get("type") == "quiz":
                if type(item.get("correct")) is not bool:
                    raise ValueError("INVALID_MASTERY_INPUT: correct must be bool")
                quiz_count += 1
                correct_count += int(item["correct"])
            elif item.get("type") == "flashcard":
                rating = item.get("rating")
                if not isinstance(rating, str) or rating not in ratings:
                    raise ValueError("INVALID_MASTERY_INPUT: invalid flashcard rating")
                flashcard_count += 1
                flashcard_total += ratings[rating]
            else:
                raise ValueError("INVALID_MASTERY_INPUT: unsupported evidence type")

        quiz_accuracy = correct_count / quiz_count if quiz_count else None
        flashcard_score = flashcard_total / flashcard_count if flashcard_count else None
        if quiz_accuracy is not None and flashcard_score is not None:
            ratio = 0.8 * quiz_accuracy + 0.2 * flashcard_score
        else:
            ratio = quiz_accuracy if quiz_accuracy is not None else flashcard_score
        score = round(ratio * 100, 2) if ratio is not None else None
        count = quiz_count + flashcard_count
        return {
            **scope,
            "mastery_score": score,
            "level": self._level(score) if score is not None else None,
            "confidence": "LOW" if count < 5 else "MEDIUM" if count < 15 else "HIGH",
            "evidence_count": count,
            "components": {
                "quiz_accuracy": quiz_accuracy,
                "quiz_evidence_count": quiz_count,
                "flashcard_score": flashcard_score,
                "flashcard_evidence_count": flashcard_count,
            },
        }
