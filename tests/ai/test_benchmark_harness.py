import json

import pytest

from backend.services.ai.benchmark_harness import (
    BenchmarkFixture,
    BenchmarkHarness,
    BenchmarkTarget,
)
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.quiz_service import QuizService


CONTEXT = "Python uses indentation to define blocks."


def quiz_payload():
    return {"questions": [{
        "question": QuizService.GROUNDING_QUESTION_PREFIX + "Python uses ____ to define blocks.",
        "type": "mcq",
        "options": [
            {"id": "A", "text": "indentation"},
            {"id": "B", "text": "braces"},
        ],
        "correct_option_id": "A",
        "explanation": "The verified excerpt contains the answer.",
        "grounding_evidence": CONTEXT,
    }]}


def flashcard_payload():
    return {"flashcards": [{
        "front_text": FlashcardService.GROUNDING_FRONT_PREFIX + "Python uses ____ to define blocks.",
        "back_text": "indentation",
        "topic": "Python",
        "difficulty": "easy",
        "grounding_evidence": CONTEXT,
    }]}


class FakeProvider:
    def __init__(self, provider, model, content, *, fail=False, secret_error=False):
        self.provider = provider
        self.model = model
        self.content = content
        self.fail = fail
        self.secret_error = secret_error
        self.calls = []

    async def generate(self, prompt, system_prompt=None, **kwargs):
        self.calls.append((prompt, system_prompt, kwargs))
        if self.secret_error:
            raise RuntimeError("SECRET_API_KEY=do-not-leak")
        if self.fail:
            return LLMResult(
                "error", self.provider, self.model, "SECRET_PROVIDER_BODY", 5.0,
                error_code="SERVICE_UNAVAILABLE",
            )
        result = LLMResult(
            "success", self.provider, self.model, json.dumps(self.content), 12.5,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        result.first_token_latency_ms = 3.5
        return result

    async def health_check(self):
        return {"provider": self.provider, "model": self.model, "status": "available"}


def fixture(task):
    return BenchmarkFixture(
        task=task,
        topic="Python",
        count=1,
        difficulty="easy",
        verified_context=CONTEXT,
        source_metadata={"course_id": "INT1339", "source_id": "lecture-1"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("task,payload", [
    ("quiz", quiz_payload()),
    ("flashcard", flashcard_payload()),
])
async def test_multiple_targets_use_same_fixture_contract_and_metrics(task, payload):
    first = FakeProvider("ollama", "qwen", payload)
    second = FakeProvider("gemini", "flash", payload)
    targets = [
        BenchmarkTarget(first, input_cost_per_million=1.0, output_cost_per_million=2.0),
        BenchmarkTarget(second, input_cost_per_million=1.0, output_cost_per_million=2.0),
    ]

    result = await BenchmarkHarness().run(fixture(task), targets)

    assert len(result["results"]) == 2
    assert first.calls[0] == second.calls[0]
    assert {item["provider"] for item in result["results"]} == {"ollama", "gemini"}
    for item in result["results"]:
        assert item["status"] == "success"
        assert item["failure_category"] is None
        assert item["structured_output_valid"] is True
        assert item["grounding_pass_rate"] == 1.0
        assert item["first_token_latency_ms"] == 3.5
        assert item["token_usage"] == {
            "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120,
        }
        assert item["estimated_cost_usd"] == pytest.approx(0.00014)
        assert item["total_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_one_target_failure_does_not_abort_run():
    failed = FakeProvider("broken", "model-a", quiz_payload(), fail=True)
    healthy = FakeProvider("healthy", "model-b", quiz_payload())

    result = await BenchmarkHarness().run(
        fixture("quiz"), [BenchmarkTarget(failed), BenchmarkTarget(healthy)]
    )

    assert [item["status"] for item in result["results"]] == ["failure", "success"]
    assert result["results"][0]["failure_category"] == "provider_failure"
    assert result["results"][1]["grounding_pass_rate"] == 1.0


@pytest.mark.asyncio
async def test_semantic_failure_is_distinct_from_structural_failure():
    unsupported = quiz_payload()
    unsupported["questions"][0]["grounding_evidence"] = "Unrelated secret context."
    semantic = FakeProvider("mock", "semantic", unsupported)
    structural = FakeProvider("mock", "structural", {"questions": []})

    result = await BenchmarkHarness().run(
        fixture("quiz"), [BenchmarkTarget(semantic), BenchmarkTarget(structural)]
    )

    assert result["results"][0]["failure_category"] == "grounding_failure"
    assert result["results"][0]["structured_output_valid"] is True
    assert result["results"][0]["grounding_pass_rate"] == 0.0
    assert result["results"][1]["failure_category"] == "structural_failure"
    assert result["results"][1]["structured_output_valid"] is False


@pytest.mark.asyncio
async def test_flashcard_semantic_failure_uses_same_grounding_category():
    unsupported = flashcard_payload()
    unsupported["flashcards"][0]["grounding_evidence"] = "Unrelated context."

    result = await BenchmarkHarness().run(
        fixture("flashcard"), [BenchmarkTarget(FakeProvider("mock", "cards", unsupported))]
    )

    assert result["results"][0]["failure_category"] == "grounding_failure"
    assert result["results"][0]["structured_output_valid"] is True
    assert result["results"][0]["grounding_pass_rate"] == 0.0


@pytest.mark.asyncio
async def test_metrics_never_include_provider_content_exception_or_secrets():
    provider = FakeProvider("SECRET provider", "SECRET model", quiz_payload(), secret_error=True)

    result = await BenchmarkHarness().run(fixture("quiz"), [BenchmarkTarget(provider)])
    encoded = json.dumps(result)

    assert result["results"][0]["provider"] == "unknown"
    assert result["results"][0]["model"] == "unknown"
    assert result["results"][0]["failure_category"] == "provider_failure"
    assert "SECRET" not in encoded
    assert "do-not-leak" not in encoded


def test_fixture_rejects_unverified_or_unsupported_inputs():
    with pytest.raises(ValueError, match="invalid benchmark fixture"):
        BenchmarkFixture(
            task="chat", topic="Python", count=1, difficulty="easy",
            verified_context=CONTEXT,
        )
    with pytest.raises(ValueError, match="invalid benchmark fixture"):
        BenchmarkFixture(
            task="quiz", topic="Python", count=1, difficulty="easy",
            verified_context=" ",
        )
