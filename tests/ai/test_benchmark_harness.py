import json

import pytest

from backend.services.ai.benchmark_harness import (
    BenchmarkFixture,
    BenchmarkHarness,
    BenchmarkTarget,
    SyntheticBenchmarkSource,
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
    def __init__(self, provider, model, content, *, fail=False, secret_error=False,
                 result_provider=None, result_model=None):
        self.provider = provider
        self.model = model
        self.content = content
        self.fail = fail
        self.secret_error = secret_error
        self.result_provider = result_provider
        self.result_model = result_model
        self.calls = []

    async def generate(self, prompt, system_prompt=None, **kwargs):
        self.calls.append((prompt, system_prompt, kwargs))
        if self.secret_error:
            raise RuntimeError("SECRET_API_KEY=do-not-leak")
        if self.fail:
            return LLMResult(
                "error", self.result_provider or self.provider,
                self.result_model or self.model, "SECRET_PROVIDER_BODY", 5.0,
                error_code="SERVICE_UNAVAILABLE",
            )
        result = LLMResult(
            "success", self.result_provider or self.provider,
            self.result_model or self.model, json.dumps(self.content), 12.5,
            usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        result.first_token_latency_ms = 3.5
        return result

    async def health_check(self):
        return {"provider": self.provider, "model": self.model, "status": "available"}


def source(course_id="INT1339", **overrides):
    values = {
        "course_id": course_id,
        "source_id": "synthetic-lecture-1",
        "content": CONTEXT,
        "version": "synthetic-v1",
    }
    values.update(overrides)
    return SyntheticBenchmarkSource(**values)


def fixture(task, *, course_id="INT1339", sources=None):
    return BenchmarkFixture(
        task=task,
        course_id=course_id,
        topic="Python",
        count=1,
        difficulty="easy",
        sources=tuple(sources or (source(course_id),)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("task,payload", [
    ("quiz", quiz_payload()),
    ("flashcard", flashcard_payload()),
])
async def test_multiple_targets_use_same_fixture_contract_and_metrics(task, payload):
    first = FakeProvider("ollama", "qwen2.5:3b", payload)
    second = FakeProvider("gemini", "gemini-2.5-flash", payload)
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
    failed = FakeProvider("ollama", "qwen2.5:3b", quiz_payload(), fail=True)
    healthy = FakeProvider("deepseek", "deepseek-chat", quiz_payload())

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
    semantic = FakeProvider("ollama", "qwen2.5:3b", unsupported)
    structural = FakeProvider("deepseek", "deepseek-chat", {"questions": []})

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
        fixture("flashcard"), [BenchmarkTarget(
            FakeProvider("ollama", "qwen2.5:3b", unsupported))]
    )

    assert result["results"][0]["failure_category"] == "grounding_failure"
    assert result["results"][0]["structured_output_valid"] is True
    assert result["results"][0]["grounding_pass_rate"] == 0.0


@pytest.mark.asyncio
async def test_metrics_never_include_provider_content_exception_or_secrets():
    provider = FakeProvider(
        "ollama", "qwen2.5:3b", quiz_payload(), secret_error=True)

    result = await BenchmarkHarness().run(fixture("quiz"), [BenchmarkTarget(provider)])
    encoded = json.dumps(result)

    assert result["results"][0]["provider"] == "ollama"
    assert result["results"][0]["model"] == "qwen2.5:3b"
    assert result["results"][0]["failure_category"] == "provider_failure"
    assert "SECRET" not in encoded
    assert "do-not-leak" not in encoded


def test_fixture_rejects_unverified_or_unsupported_inputs():
    with pytest.raises(ValueError, match="invalid benchmark fixture"):
        BenchmarkFixture(
            task="chat", course_id="INT1339", topic="Python", count=1,
            difficulty="easy", sources=(source(),),
        )
    with pytest.raises(ValueError, match="invalid benchmark fixture"):
        BenchmarkFixture(
            task="quiz", course_id="INT1339", topic="Python", count=1,
            difficulty="easy", sources=(),
        )


@pytest.mark.asyncio
async def test_cross_course_source_is_rejected_before_provider_invocation():
    provider = FakeProvider("ollama", "qwen2.5:3b", quiz_payload())
    benchmark_fixture = fixture("quiz", course_id="INT1339")
    object.__setattr__(benchmark_fixture.sources[0], "course_id", "INT2001")

    with pytest.raises(ValueError, match="^invalid benchmark fixture$"):
        await BenchmarkHarness().run(
            benchmark_fixture, [BenchmarkTarget(provider)])

    assert provider.calls == []


@pytest.mark.asyncio
async def test_inactive_source_is_rejected_before_provider_invocation():
    provider = FakeProvider("ollama", "qwen2.5:3b", quiz_payload())
    benchmark_fixture = fixture("quiz")
    object.__setattr__(benchmark_fixture.sources[0], "status", "INACTIVE")

    with pytest.raises(ValueError, match="^invalid benchmark fixture$"):
        await BenchmarkHarness().run(
            benchmark_fixture, [BenchmarkTarget(provider)])

    assert provider.calls == []


@pytest.mark.asyncio
async def test_arbitrary_or_inconsistent_metadata_cannot_bypass_source_validation():
    provider = FakeProvider("ollama", "qwen2.5:3b", quiz_payload())
    benchmark_fixture = fixture("quiz")
    object.__setattr__(benchmark_fixture.sources[0], "content_sha256", "0" * 64)

    with pytest.raises(ValueError, match="^invalid benchmark fixture$"):
        await BenchmarkHarness().run(
            benchmark_fixture, [BenchmarkTarget(provider)])
    with pytest.raises(TypeError):
        BenchmarkFixture(
            task="quiz", course_id="INT1339", topic="Python", count=1,
            difficulty="easy", sources=(source(),),
            source_metadata={"course_id": "INT2001", "status": "ACTIVE"},
        )

    assert provider.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
@pytest.mark.parametrize(("configured_provider", "configured_model"), [
    ("ollama", "qwen2.5:3b"),
    ("fallback", "provider-chain"),
])
async def test_raw_token_shaped_result_identity_never_reaches_report_or_errors(
        fail, configured_provider, configured_model):
    token = "sk-private-token"
    provider = FakeProvider(
        configured_provider, configured_model, quiz_payload(),
        fail=fail, result_provider=token, result_model=token,
    )

    result = await BenchmarkHarness().run(
        fixture("quiz"), [BenchmarkTarget(provider)]
    )
    encoded = json.dumps(result)

    assert result["results"][0]["provider"] == configured_provider
    assert result["results"][0]["model"] == configured_model
    assert result["results"][0]["status"] == ("failure" if fail else "success")
    assert token not in encoded

    with pytest.raises(ValueError) as raised:
        BenchmarkTarget(FakeProvider(token, token, quiz_payload()))
    assert str(raised.value) == "unsupported benchmark target"
    assert token not in str(raised.value)
