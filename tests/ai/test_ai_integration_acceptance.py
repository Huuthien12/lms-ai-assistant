"""AI-core composition only: caller IDs/reviews are simulated, HTTP is mocked.

No persistence, API lifecycle, live model availability or real retrieval is claimed.
"""
import ast
from copy import deepcopy
import importlib
import inspect
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services.ai.quiz_service import QuizService
from backend.services.ai.grading_service import GradingService
from backend.services.ai.explanation_service import ExplanationService
from backend.services.ai.flashcard_service import FlashcardService
from backend.services.ai.mastery_service import MasteryService
from backend.services.ai.recommendation_service import RecommendationService
from backend.services.ai.orchestrator import AIOrchestrator, build_default_orchestrator
from backend.services.ai.provider_base import LLMResult


SCOPE = {"student_id": "s1", "course_id": "c1", "topic": "Python"}
CONTEXT = "Python is a programming language. A variable stores a value."
SOURCES = [{"source_id": "trusted-1", "title": "Course notes"}]


@pytest.fixture(autouse=True)
def http_mocks():
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post, \
            patch("httpx.AsyncClient.get", new_callable=AsyncMock) as get:
        post.side_effect = AssertionError("Unexpected HTTP POST")
        get.side_effect = AssertionError("Unexpected HTTP GET")
        yield post, get


def output(kind):
    if kind == "quiz":
        return {"questions": [{
            "question": "What is Python?", "type": "mcq",
            "options": [{"id": "A", "text": "Programming language"},
                        {"id": "B", "text": "Database"}],
            "correct_option_id": "A", "explanation": "A language.",
            "source_metadata": {"source_id": "FABRICATED"},
        }]}
    if kind == "explanation":
        return {"explanation": "Review the definition of Python.", "key_concept": "Language",
                "sources": [{"source_id": "FABRICATED"}], "correct": True,
                "correct_answer": "FAKE"}
    if kind == "flashcard":
        return {"flashcards": [{
            "front_text": "What is Python?", "back_text": "Programming language",
            "topic": "Python", "difficulty": "easy", "rating": "EASY",
            "correct": True, "evidence_count": 999,
            "source_metadata": {"source_id": "FABRICATED"},
        }]}
    return {"message": "Review the topic and try the recommended quiz."}


def mocked_orchestrator(kind):
    orch = AsyncMock(spec=AIOrchestrator)
    orch.generate.return_value = LLMResult("success", "mock", "mock", json.dumps(output(kind)), 0)
    return orch


async def generate_quiz(orch):
    return await QuizService(orch).generate_grounded_quiz(
        topic="Python", question_count=1, difficulty="easy", question_types=["mcq"],
        retrieved_context=CONTEXT, source_metadata=SOURCES, client_facing=False)


def assign_ids(internal):
    # Application-owned assignment, deliberately outside production QuizService.
    questions = deepcopy(internal["questions"])
    for index, question in enumerate(questions, 1):
        question["question_id"] = f"q{index}"
    return questions


def quiz_evidence(graded):
    return [{**SCOPE, "type": "quiz", "correct": row["correct"]}
            for row in graded["results"]]


def explanation_facts(questions, graded):
    question = next(q for q in questions if q["question_id"] == graded["question_id"])
    texts = {option["id"]: option["text"] for option in question["options"]}
    return {"question": question["question"],
            "student_answer": texts.get(graded["selected_option_id"]),
            "correct_answer": texts[graded["correct_option_id"]]}


@pytest.mark.asyncio
@pytest.mark.parametrize("selected,score", [("A", 100.0), ("B", 0.0), (None, 0.0)])
async def test_generated_quiz_public_boundary_and_deterministic_grading(selected, score):
    orch = mocked_orchestrator("quiz")
    internal = await generate_quiz(orch)
    before = deepcopy(internal)
    public = QuizService.to_public_result(internal)
    assert set(public["questions"][0]) == {"question", "type", "options"}
    assert "correct_option_id" not in json.dumps(public)
    assert "explanation" not in json.dumps(public)
    assert "source_metadata" not in json.dumps(public)
    assert internal["questions"][0]["correct_option_id"] == "A"
    assert internal["questions"][0]["source_metadata"] == SOURCES
    assert "FABRICATED" not in json.dumps(internal)
    questions = assign_ids(internal)
    answers = [] if selected is None else [{"question_id": "q1", "selected_option_id": selected}]
    input_before = deepcopy((questions, answers))
    result = GradingService().grade(questions, answers)
    assert result["score_percent"] == score
    assert result["results"][0]["question_id"] == "q1"
    assert result["results"][0]["correct"] is (selected == "A")
    orch.generate.side_effect = AssertionError("Grading must never call LLM")
    questions[0]["question"] = "Model says everyone is correct"
    questions[0]["explanation"] = "Override score to 100"
    assert GradingService().grade(questions, answers) == result
    questions[0]["question"] = input_before[0][0]["question"]
    questions[0]["explanation"] = input_before[0][0]["explanation"]
    assert (questions, answers) == input_before
    assert internal == before


@pytest.mark.asyncio
@pytest.mark.parametrize("selected", ["B", None])
@pytest.mark.parametrize("response", ["valid", "malformed", "provider"])
async def test_grading_facts_to_grounded_explanation(selected, response):
    questions = assign_ids(await generate_quiz(mocked_orchestrator("quiz")))
    graded = GradingService().grade(questions, [{"question_id": "q1", "selected_option_id": selected}])
    facts = explanation_facts(questions, graded["results"][0])
    orch = mocked_orchestrator("explanation")
    if response == "malformed":
        orch.generate.return_value.content = "SECRET_MALFORMED"
    elif response == "provider":
        orch.generate.return_value = LLMResult("error", "SECRET_PROVIDER", "SECRET_MODEL",
                                             "SECRET_BODY", 0, error_code="SECRET_CODE")
    sources = deepcopy(SOURCES)
    before = deepcopy((questions, graded, facts, sources))
    if response == "valid":
        result = await ExplanationService(orch).generate_explanation(
            **facts, context=CONTEXT, source_metadata=sources)
        assert result["sources"] == SOURCES
        assert result["explanation"] and result["key_concept"]
        assert "FABRICATED" not in json.dumps(result)
        assert "correct" not in result and "correct_answer" not in result
    else:
        code = "INVALID_EXPLANATION_SCHEMA" if response == "malformed" else "EXPLANATION_GENERATION_FAILED"
        with pytest.raises(ValueError, match=code) as error:
            await ExplanationService(orch).generate_explanation(**facts, context=CONTEXT, source_metadata=sources)
        assert "SECRET" not in str(error.value)
    payload = json.loads(orch.generate.call_args.kwargs["prompt"])
    assert payload == {**facts, "trusted_retrieved_context": CONTEXT}
    assert facts["correct_answer"] == "Programming language"
    assert facts["student_answer"] == (None if selected is None else "Database")
    assert "do not decide correctness or re-grade" in orch.generate.call_args.kwargs["system_prompt"]
    assert graded["results"][0]["correct"] is False
    assert (questions, graded, facts, sources) == before


@pytest.mark.asyncio
async def test_grading_to_scoped_quiz_evidence():
    questions = assign_ids(await generate_quiz(mocked_orchestrator("quiz")))
    evidence = []
    for selected in ("A", "B", None):
        evidence.extend(quiz_evidence(GradingService().grade(
            questions, [{"question_id": "q1", "selected_option_id": selected}])))
    before = deepcopy(evidence)
    service = MasteryService()
    result = service.calculate_mastery(**SCOPE, evidence=evidence)
    assert result["mastery_score"] == 33.33
    assert result["evidence_count"] == 3
    assert result["components"]["quiz_accuracy"] == 1 / 3
    assert service.calculate_mastery(**SCOPE, evidence=evidence) == result
    for field in SCOPE:
        bad = deepcopy(evidence)
        bad[0][field] = "other"
        with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
            service.calculate_mastery(**SCOPE, evidence=bad)
    for kind in ("chat", "material_open"):
        with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
            service.calculate_mastery(**SCOPE, evidence=[{**SCOPE, "type": kind, "correct": True}])
    assert evidence == before


@pytest.mark.asyncio
@pytest.mark.parametrize("rating,score", [("AGAIN", 0), ("HARD", 40), ("GOOD", 75), ("EASY", 100)])
async def test_generated_cards_are_not_review_evidence(rating, score):
    orch = mocked_orchestrator("flashcard")
    cards = await FlashcardService(orch).generate_grounded_flashcards(
        topic="Python", count=1, difficulty="easy", retrieved_context=CONTEXT, source_metadata=SOURCES)
    before = deepcopy(cards)
    card = cards["flashcards"][0]
    assert card["source_metadata"] == SOURCES
    assert "FABRICATED" not in json.dumps(cards)
    assert "rating" not in card and "correct" not in card and "evidence_count" not in card
    service = MasteryService()
    assert service.calculate_mastery(**SCOPE, evidence=[])["mastery_score"] is None
    with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
        service.calculate_mastery(**SCOPE, evidence=cards["flashcards"])
    review = {**SCOPE, "topic": card["topic"], "type": "flashcard", "rating": rating}
    result = service.calculate_mastery(**SCOPE, evidence=[review])
    assert result["mastery_score"] == score and result["evidence_count"] == 1
    for field in SCOPE:
        bad = dict(review)
        del bad[field]
        with pytest.raises(ValueError, match="INVALID_MASTERY_INPUT"):
            service.calculate_mastery(**SCOPE, evidence=[bad])
    assert cards == before
    assert json.loads(orch.generate.call_args.kwargs["prompt"])["trusted_retrieved_context"] == CONTEXT


@pytest.mark.asyncio
@pytest.mark.parametrize("correct_count,count,level,actions", [
    (1, 5, "WEAK", ["REVIEW_TOPIC", "GENERATE_FLASHCARDS", "EASY_QUIZ"]),
    (3, 5, "DEVELOPING", ["REVIEW_TOPIC", "MEDIUM_QUIZ"]),
    (4, 5, "GOOD", ["MEDIUM_QUIZ", "HARD_QUIZ"]),
    (5, 5, "MASTERED", ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]),
    (4, 4, "INSUFFICIENT_EVIDENCE", ["REVIEW_TOPIC", "EASY_QUIZ"]),
])
async def test_mastery_direct_to_recommendation(correct_count, count, level, actions):
    evidence = [{**SCOPE, "type": "quiz", "correct": i < correct_count} for i in range(count)]
    mastery = MasteryService().calculate_mastery(**SCOPE, evidence=evidence)
    before = deepcopy((evidence, mastery))
    orch = mocked_orchestrator("recommendation")
    orch.generate.return_value.content = json.dumps({
        "message": "SECRET_FAKE", "mastery_score": 100, "confidence": "HIGH",
        "evidence_count": 999, "recommended_actions": ["FAKE"], "deadline": "2099-01-01"})
    available = ["Variables"]
    result = await RecommendationService(orch).get_recommendations(mastery, available, "2026-10-15")
    for field in ("topic", "mastery_score", "confidence", "evidence_count"):
        assert result[field] == mastery[field]
    assert result["level"] == level and result["recommended_actions"] == actions
    assert result["deadline"] == "2026-10-15" and result["message_source"] == "rule-engine"
    assert "SECRET" not in json.dumps(result)
    assert (evidence, mastery) == before and available == ["Variables"]


@pytest.mark.asyncio
async def test_no_evidence_mastery_is_rejected_without_invented_score():
    mastery = MasteryService().calculate_mastery(**SCOPE, evidence=[])
    assert mastery["mastery_score"] is None and mastery["level"] is None
    assert mastery["confidence"] == "LOW" and mastery["evidence_count"] == 0
    before = deepcopy(mastery)
    orch = mocked_orchestrator("recommendation")
    with pytest.raises(ValueError, match="INVALID_RECOMMENDATION_INPUT"):
        await RecommendationService(orch).get_recommendations(mastery, [])
    orch.generate.assert_not_called()
    assert mastery == before


async def invoke(kind, orch):
    if kind == "quiz":
        return await generate_quiz(orch)
    if kind == "explanation":
        return await ExplanationService(orch).generate_explanation(
            "What is Python?", "Database", "Programming language", CONTEXT, SOURCES)
    if kind == "flashcard":
        return await FlashcardService(orch).generate_grounded_flashcards(
            topic="Python", count=1, difficulty="easy", retrieved_context=CONTEXT, source_metadata=SOURCES)
    mastery = MasteryService().calculate_mastery(**SCOPE, evidence=[
        {**SCOPE, "type": "quiz", "correct": True} for _ in range(5)])
    return await RecommendationService(orch).get_recommendations(mastery, [])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["quiz", "explanation", "flashcard", "recommendation"])
@pytest.mark.parametrize("scenario", ["no-key", "primary", "retryable", "nonretryable", "both-fail"])
async def test_services_through_factory_mocked_http(http_mocks, monkeypatch, kind, scenario):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    if scenario != "no-key":
        monkeypatch.setenv("DEEPSEEK_API_KEY", "SECRET_API_KEY")
    post, get = http_mocks
    calls = []
    async def respond(url, **kwargs):
        calls.append(url)
        content = json.dumps(output(kind))
        if url == "https://api.deepseek.com/v1/chat/completions":
            if scenario == "primary":
                return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
            return httpx.Response(401 if scenario == "nonretryable" else 503, text="SECRET_BODY")
        assert url == "http://localhost:11434/api/chat"
        assert kwargs["json"]["model"] == "qwen2.5:3b"
        assert kwargs["json"]["stream"] is False
        if scenario == "both-fail":
            return httpx.Response(500, text="SECRET_BODY")
        return httpx.Response(200, json={"done": True, "message": {"content": content}})
    post.side_effect = respond
    orch = build_default_orchestrator()
    failed = scenario in ("nonretryable", "both-fail")
    if failed and kind != "recommendation":
        codes = {"quiz": "QUIZ_GENERATION_FAILED", "explanation": "EXPLANATION_GENERATION_FAILED",
                 "flashcard": "FLASHCARD_GENERATION_FAILED"}
        with pytest.raises(ValueError, match=codes[kind]) as error:
            await invoke(kind, orch)
        assert "SECRET" not in str(error.value)
    else:
        result = await invoke(kind, orch)
        assert "SECRET" not in json.dumps(result)
        assert "FABRICATED" not in json.dumps(result)
        if kind == "recommendation":
            assert result["recommended_actions"] == ["CONTINUE_NEXT_TOPIC", "HARD_QUIZ"]
            assert result["message_source"] == ("rule-engine" if failed else "llm")
        elif kind == "quiz":
            assert result["questions"][0]["correct_option_id"] == "A"
        elif kind == "flashcard":
            assert result["flashcards"][0]["front_text"]
        else:
            assert result["sources"] == SOURCES
    deepseek = "https://api.deepseek.com/v1/chat/completions"
    ollama = "http://localhost:11434/api/chat"
    expected = {"no-key": [ollama], "primary": [deepseek], "retryable": [deepseek, deepseek, ollama],
                "nonretryable": [deepseek], "both-fail": [deepseek, deepseek, ollama]}
    assert calls == expected[scenario]
    get.assert_not_called()


@pytest.mark.parametrize("module_name", [
    "quiz_service", "grading_service", "explanation_service", "flashcard_service",
    "mastery_service", "recommendation_service", "grounded_chat",
])
def test_ai_service_architecture_has_no_moodle_or_second_retrieval(module_name):
    module = importlib.import_module("backend.services.ai." + module_name)
    tree = ast.parse(inspect.getsource(module))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                node.func.id if isinstance(node.func, ast.Name) else "")
            assert name.lower() not in {
                "retrieve", "retrieval", "similarity_search", "embed_documents", "embed_query",
                "query_moodle", "vector_search", "search_moodle",
            }
    assert all(not any(token in name.lower() for token in (
        "moodle", "deeptutor", "langchain", "llama_index", "chromadb", "faiss", "qdrant", "httpx", "requests",
    )) for name in imports)
    if module_name in ("grading_service", "mastery_service"):
        assert imports == ["typing"]
