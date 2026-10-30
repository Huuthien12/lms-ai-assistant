import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.ai.grading_service import GradingService
from backend.services.ai.orchestrator import AIOrchestrator
from backend.services.ai.provider_base import LLMResult
from backend.services.ai.quiz_service import QuizService, schema_log_fields


PREFIX = "Complete the missing text in this exact excerpt from the verified source: "
CONTEXT = "Python is a programming language. Variables store values."


def question(evidence="Python is a programming language.", answer="programming language",
             *, text=None, correct_id="supported",source_id=None):
    cloze = evidence.replace(answer, "____", 1)
    result={
        "question": text or PREFIX + cloze,
        "type": "mcq",
        "options": [
            {"id": correct_id, "text": answer},
            {"id": "distractor", "text": "database"},
        ],
        "correct_option_id": correct_id,
        "explanation": "The missing text is copied from the verified excerpt.",
        "grounding_evidence": evidence,
    }
    if source_id is not None: result["source_id"]=source_id
    return result


def service_with(*questions):
    orchestrator = MagicMock(spec=AIOrchestrator)
    orchestrator.generate = AsyncMock(return_value=LLMResult(
        "success", "test", "test", json.dumps({"questions": list(questions)}), 0))
    return QuizService(orchestrator), orchestrator


def evidence_first_question(candidate, *, number=1):
    return {
        "question": f"Nội dung nào được nêu trong tài liệu ở ý {number}?",
        "type": "mcq",
        "evidence_id": candidate["evidence_id"],
        "answer_span_id": candidate["answer_span_id"],
        "options": [
            {"id": "A", "text": candidate["text"]},
            {"id": "B", "text": f"distractor-{number}-b"},
            {"id": "C", "text": f"distractor-{number}-c"},
            {"id": "D", "text": f"distractor-{number}-d"},
        ],
        "correct_option_id": "A",
        "explanation": "Đáp án được sao chép từ evidence đã xác minh.",
    }


async def generate(service, *, count=1, context=CONTEXT, source_metadata=None):
    return await service.generate_grounded_quiz(
        topic="Python", question_count=count, difficulty="easy",
        question_types=["mcq"], retrieved_context=context,
        source_metadata=source_metadata, client_facing=False,
    )


@pytest.mark.asyncio
async def test_exact_source_cloze_and_key_are_accepted_but_remain_private():
    context = "[source-1]\nPython uses return to leave a function."
    sources = [{"source_id": "source-1"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    candidate = QuizService._select_question_candidates(
        QuizService._answer_span_snapshot(evidence), 1)[0]
    service, _ = service_with(evidence_first_question(candidate))
    internal = await generate(service, context=context, source_metadata=sources)
    assert internal["questions"][0]["grounding_evidence"] == evidence[0]["evidence"]
    public = service.to_public_result(internal)
    encoded = json.dumps(public)
    assert "correct_option_id" not in encoded
    assert "grounding_evidence" not in encoded
    assert "explanation" not in encoded


@pytest.mark.asyncio
async def test_structurally_valid_question_outside_verified_context_fails_closed():
    unsupported = question("The moon is made of cheese.", "cheese")
    service, _ = service_with(unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_mixed_quiz_with_one_unsupported_question_is_rejected_as_a_unit():
    unsupported = question("The moon is made of cheese.", "cheese")
    service, _ = service_with(question(), unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, count=2)


@pytest.mark.asyncio
async def test_freeform_question_cannot_borrow_an_unrelated_valid_quote():
    candidate = question(text="Which database is implemented by Python?")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_correct_option_must_be_the_unique_missing_source_span():
    candidate = question(answer="high-level programming language")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service)


@pytest.mark.asyncio
async def test_overlapping_answer_occurrences_are_ambiguous_and_rejected():
    candidate = question("aaa fact", "aa")
    service, _ = service_with(candidate)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, context="aaa fact")


@pytest.mark.asyncio
async def test_untrusted_cross_course_metadata_cannot_expand_grounding_context():
    unsupported = question("Databases use structured query language.", "structured query language")
    service, _ = service_with(unsupported)
    with pytest.raises(ValueError, match="^INVALID_QUIZ_SCHEMA"):
        await generate(service, source_metadata=[{
            "course_id": "OTHER", "untrusted_excerpt": unsupported["grounding_evidence"],
        }])


@pytest.mark.asyncio
async def test_source_id_must_match_the_verified_source_block():
    context="[source-1]\nPython is a programming language.\n\n[source-2]\nVariables store values."
    sources=[{"source_id":"source-1"},{"source_id":"source-2"}]
    evidence=QuizService._evidence_snapshot(context,sources)
    candidate=QuizService._select_question_candidates(QuizService._answer_span_snapshot(evidence),1)[0]
    service,_=service_with(evidence_first_question(candidate))
    internal=await generate(service,context=context,source_metadata=sources)
    assert internal["questions"][0]["grounding_source_id"]=="source-1"
    assert internal["questions"][0]["source_metadata"]==[{"source_id":"source-1"}]
    mismatched=evidence_first_question(candidate)
    mismatched["evidence_id"]="e2"
    service,_=service_with(mismatched)
    with pytest.raises(ValueError,match="^INVALID_QUIZ_SCHEMA"):
        await generate(service,context=context,source_metadata=sources)


@pytest.mark.parametrize(("candidate", "reason"), [
    (question(), "missing_source_id"),
    (question(source_id="missing"), "source_id_not_in_snapshot"),
    (question(source_id="source-1", evidence="Variables store values.", answer="store values"), "evidence_not_exact"),
    (question(source_id="source-1", evidence="Python Python", answer="Python"), "evidence_not_exact"),
])
def test_grounding_failures_keep_only_safe_diagnostics(candidate, reason):
    context = "[source-1]\nPython is a programming language.\n\n[source-2]\nVariables store values."
    diagnostics = {}
    with pytest.raises(ValueError) as raised:
        QuizService.validate_and_parse_quiz(
            json.dumps({"questions": [candidate]}), question_count=1,
            source_metadata=[{"source_id": "source-1"}, {"source_id": "source-2"}],
            grounding_context=context, _diagnostics=diagnostics)
    assert raised.value.diagnostics["grounding_failure_reason"] == reason
    assert raised.value.diagnostics["requested_count"] == 1
    assert raised.value.diagnostics["validated_count"] == 0
    assert "Python is a programming language" not in str(raised.value.diagnostics)


def test_repeated_answer_is_classified_without_content():
    repeated = question("Python is Python.", "Python")
    diagnostics = {}
    with pytest.raises(ValueError) as raised:
        QuizService.validate_and_parse_quiz(json.dumps({"questions": [repeated]}), question_count=1,
                                             grounding_context="Python is Python.", _diagnostics=diagnostics)
    assert raised.value.diagnostics["grounding_failure_reason"] == "answer_not_unique"
    assert raised.value.diagnostics["answer_occurrence_count"] == 2


def test_backend_rebuilds_a_valid_cloze_instead_of_trusting_model_wording():
    wrong = question(text=PREFIX + "Python is a ____ language.")
    result = QuizService.validate_and_parse_quiz(json.dumps({"questions": [wrong]}), question_count=1,
                                                 grounding_context=CONTEXT)
    assert result["questions"][0]["question"] == PREFIX + "Python is a ____."


def test_evidence_first_accepts_natural_vietnamese_question_with_four_abcd_options():
    context = "[source-1]\nPhương thức startswith kiểm tra chuỗi có bắt đầu bằng tiền tố xác định."
    snapshot = QuizService._evidence_snapshot(context, [{"source_id": "source-1"}])
    raw = {"questions": [{
        "question": "Trong Python, phương thức nào kiểm tra chuỗi có bắt đầu bằng tiền tố xác định?",
        "type": "mcq", "evidence_id": "e1",
        "options": [{"id": "A", "text": "startswith"}, {"id": "B", "text": "endswith"},
                    {"id": "C", "text": "split"}, {"id": "D", "text": "replace"}],
        "correct_option_id": "A", "explanation": "startswith phù hợp với nội dung tài liệu.",
    }]}
    result = QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
        source_metadata=[{"source_id": "source-1"}], grounding_context=context,
        evidence_snapshot=snapshot)
    assert result["questions"][0]["question"] == raw["questions"][0]["question"]
    assert [option["id"] for option in result["questions"][0]["options"]] == ["A", "B", "C", "D"]


def test_evidence_first_rejects_non_abcd_or_two_options():
    context = "[source-1]\nPhương thức startswith kiểm tra chuỗi có bắt đầu bằng tiền tố xác định."
    snapshot = QuizService._evidence_snapshot(context, [{"source_id": "source-1"}])
    raw = question("Phương thức startswith kiểm tra chuỗi có bắt đầu bằng tiền tố xác định.", "startswith",
                   text="Phương thức nào kiểm tra tiền tố?", source_id="source-1")
    raw["evidence_id"] = "e1"
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA"):
        QuizService.validate_and_parse_quiz(json.dumps({"questions": [raw]}), question_count=1,
            source_metadata=[{"source_id": "source-1"}], grounding_context=context,
            evidence_snapshot=snapshot)


def test_answer_span_first_requires_the_verified_span_as_correct_option():
    context = "[source-1]\nThe client-server architecture separates client and server responsibilities."
    sources = [{"source_id": "source-1"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)
    span = next(item for item in spans if item["text"] == "client-server")
    raw = {"questions": [{
        "question": "Trong kiến trúc web, thành phần nào được nêu trong tài liệu?", "type": "mcq",
        "evidence_id": span["evidence_id"], "answer_span_id": span["answer_span_id"],
        "options": [{"id": "A", "text": "client-server"}, {"id": "B", "text": "database"},
                    {"id": "C", "text": "browser"}, {"id": "D", "text": "network"}],
        "correct_option_id": "A", "explanation": "client-server xuất hiện trong evidence.",
    }]}
    accepted = QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
        source_metadata=sources, grounding_context=context, evidence_snapshot=evidence, answer_spans=spans)
    assert accepted["questions"][0]["correct_option_id"] == "A"
    raw["questions"][0]["options"][0]["text"] = "architecture"
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as error:
        QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
            source_metadata=sources, grounding_context=context, evidence_snapshot=evidence, answer_spans=spans)
    assert error.value.diagnostics["grounding_failure_reason"] == "answer_span_mismatch"
    assert error.value.diagnostics["evidence_id"] == span["evidence_id"]
    assert error.value.diagnostics["answer_span_id"] == span["answer_span_id"]
    assert schema_log_fields(error.value)["evidence_id"] == span["evidence_id"]
    assert schema_log_fields(error.value)["answer_span_id"] == span["answer_span_id"]


def test_answer_span_first_restores_verified_spelling_for_presentation_only_difference():
    context = "[source-1]\nThe Client-Server architecture separates client and server responsibilities."
    sources = [{"source_id": "source-1"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)
    span = next(item for item in spans if item["text"] == "Client-Server")
    raw = {"questions": [{
        "question": "Thành phần nào được nêu trong tài liệu?", "type": "mcq",
        "evidence_id": span["evidence_id"], "answer_span_id": span["answer_span_id"],
        "options": [{"id": "A", "text": "client-server"}, {"id": "B", "text": "database"},
                    {"id": "C", "text": "browser"}, {"id": "D", "text": "network"}],
        "correct_option_id": "A", "explanation": "Đáp án xuất hiện trong evidence.",
    }]}
    accepted = QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
        source_metadata=sources, grounding_context=context, evidence_snapshot=evidence, answer_spans=spans)
    assert accepted["questions"][0]["options"][0]["text"] == "Client-Server"


def test_answer_span_first_recovers_only_an_unambiguous_bad_identifier():
    context = "[source-1]\nThe client-server architecture separates client and server responsibilities."
    sources = [{"source_id": "source-1"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)
    span = next(item for item in spans if item["text"] == "client-server")
    raw = {"questions": [{
        "question": "Kiến trúc nào được nêu trong tài liệu?", "type": "mcq",
        "evidence_id": span["evidence_id"], "answer_span_id": "mistyped-id",
        "options": [{"id": "A", "text": "client-server"}, {"id": "B", "text": "database"},
                    {"id": "C", "text": "browser"}, {"id": "D", "text": "network"}],
        "correct_option_id": "A", "explanation": "Đáp án có trong evidence.",
    }]}
    result = QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
        source_metadata=sources, grounding_context=context, evidence_snapshot=evidence, answer_spans=spans)
    assert result["questions"][0]["options"][0]["text"] == "client-server"


def test_answer_span_snapshot_keeps_vietnamese_phrases_not_word_fragments():
    snapshot = QuizService._evidence_snapshot("[source-1]\nHàm kiểm tra chuỗi bắt đầu bằng tiền tố.", [{"source_id": "source-1"}])
    spans = QuizService._answer_span_snapshot(snapshot)
    assert any("kiểm tra" in span["text"] for span in spans)
    assert not any(span["text"] == "kiểm" for span in spans)


@pytest.mark.parametrize("evidence, required, rejected", [
    ("Danh từ xác định tên của đối tượng.", "Danh từ", "Danh"),
    ("Phân trang chia kết quả thành nhiều trang.", "Phân trang", "Phân"),
    ("Lọc dữ liệu giới hạn các bản ghi hiển thị.", "Lọc dữ liệu", "Lọc"),
    ("Sắp xếp dữ liệu theo một tiêu chí.", "Sắp xếp", "Sắp"),
])
def test_answer_span_snapshot_rejects_truncated_vietnamese_concepts(evidence, required, rejected):
    snapshot = QuizService._evidence_snapshot("[source-1]\n" + evidence, [{"source_id": "source-1"}])
    texts = [span["text"] for span in QuizService._answer_span_snapshot(snapshot)]
    assert any(required in text for text in texts)
    assert rejected not in texts


def test_answer_span_snapshot_keeps_single_token_technical_identifiers():
    snapshot = QuizService._evidence_snapshot("[source-1]\nREST uses GET with ProblemDetails for API errors.", [{"source_id": "source-1"}])
    texts = [span["text"] for span in QuizService._answer_span_snapshot(snapshot)]
    assert {"REST", "GET", "ProblemDetails"} <= set(texts)


def test_answer_span_snapshot_keeps_python_keywords_builtins_and_expressions():
    snapshot = QuizService._evidence_snapshot(
        "[source-1]\ndef value(): return len(range(3))\ncontinue breaks no loop.", [{"source_id": "source-1"}])
    texts = {span["text"] for span in QuizService._answer_span_snapshot(snapshot)}
    assert {"def", "return", "continue", "len", "range"} <= texts


def test_answer_span_candidates_do_not_cross_punctuation_or_consume_an_entire_evidence_unit():
    spans = QuizService._answer_span_snapshot([
        {"evidence_id": "e1", "source_id": "source-1", "evidence": "GET. POST handles requests."},
        {"evidence_id": "e2", "source_id": "source-1", "evidence": "Phân trang"},
    ])
    texts = {span["text"] for span in spans}
    assert "GET POST" not in texts
    assert "Phân trang" not in texts
    assert "GET" in texts and "POST" in texts


def test_verified_evidence_requires_evidence_id_instead_of_legacy_grounding_fallback():
    context = "[source-1]\nPython uses return to leave a function."
    sources = [{"source_id": "source-1"}]
    snapshot = QuizService._evidence_snapshot(context, sources)
    raw = {"questions": [{
        "question": "Từ khóa nào rời hàm?", "type": "mcq",
        "options": [{"id": "A", "text": "return"}, {"id": "B", "text": "break"},
                    {"id": "C", "text": "continue"}, {"id": "D", "text": "pass"}],
        "correct_option_id": "A", "explanation": "return có trong evidence.",
        "grounding_evidence": "Python uses return to leave a function.",
    }]}
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as error:
        QuizService.validate_and_parse_quiz(json.dumps(raw), question_count=1,
            source_metadata=sources, grounding_context=context, evidence_snapshot=snapshot,
            answer_spans=QuizService._answer_span_snapshot(snapshot))
    assert error.value.diagnostics["grounding_failure_reason"] == "evidence_id_not_in_snapshot"


def test_three_evidence_first_questions_are_accepted_only_with_matching_spans():
    context = "[chapter-s03]\nREST resources use HTTP methods and status codes for API interactions."
    sources = [{"source_id": "chapter-s03"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)[:3]
    assert len(spans) == 3
    questions=[]
    for number, span in enumerate(spans, 1):
        questions.append({
            "question": f"Thuật ngữ nào được nêu trong tài liệu REST ở ý {number}?", "type": "mcq",
            "evidence_id": span["evidence_id"], "answer_span_id": span["answer_span_id"],
            "options": [{"id": "A", "text": span["text"]}, {"id": "B", "text": f"wrong-{number}-b"},
                        {"id": "C", "text": f"wrong-{number}-c"}, {"id": "D", "text": f"wrong-{number}-d"}],
            "correct_option_id": "A", "explanation": "Đáp án được sao chép từ evidence.",
        })
    result = QuizService.validate_and_parse_quiz(json.dumps({"questions": questions}), question_count=3,
        source_metadata=sources, grounding_context=context, evidence_snapshot=evidence, answer_spans=QuizService._answer_span_snapshot(evidence))
    assert len(result["questions"]) == 3


def test_batch_semantic_validation_counts_valid_and_invalid_questions_without_persisting_them():
    context = "[chapter-s03]\nREST resources use HTTP methods and status codes for API interactions."
    sources = [{"source_id": "chapter-s03"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)[:2]
    questions=[]
    for number, span in enumerate(spans, 1):
        answer = span["text"] if number == 1 else "paraphrased-answer"
        questions.append({
            "question": f"Câu REST độc lập {number}?", "type": "mcq",
            "evidence_id": span["evidence_id"], "answer_span_id": span["answer_span_id"],
            "options": [{"id": "A", "text": answer}, {"id": "B", "text": f"wrong-{number}-b"},
                        {"id": "C", "text": f"wrong-{number}-c"}, {"id": "D", "text": f"wrong-{number}-d"}],
            "correct_option_id": "A", "explanation": "Evidence-first fixture.",
        })
    diagnostics={}
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as error:
        QuizService.validate_and_parse_quiz(json.dumps({"questions": questions}), question_count=2,
            source_metadata=sources, grounding_context=context, evidence_snapshot=evidence,
            answer_spans=QuizService._answer_span_snapshot(evidence), _diagnostics=diagnostics)
    assert error.value.diagnostics["grounding_failure_reason"] == "answer_span_mismatch"
    assert error.value.diagnostics["validated_count"] == 1
    assert error.value.diagnostics["requested_count"] == 2
    assert error.value.diagnostics["rejected_count"] == 1
    assert diagnostics["semantic_result"] == "rejected"


def test_batch_semantic_validation_reports_two_invalid_questions():
    context = "[chapter-s03]\nREST resources use HTTP methods and status codes for API interactions."
    sources = [{"source_id": "chapter-s03"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    spans = QuizService._answer_span_snapshot(evidence)[:2]
    questions=[{
        "question": f"Câu REST không hợp lệ {number}?", "type": "mcq",
        "evidence_id": span["evidence_id"], "answer_span_id": span["answer_span_id"],
        "options": [{"id": "A", "text": f"wrong-{number}"}, {"id": "B", "text": f"b-{number}"},
                    {"id": "C", "text": f"c-{number}"}, {"id": "D", "text": f"d-{number}"}],
        "correct_option_id": "A", "explanation": "Evidence-first fixture.",
    } for number, span in enumerate(spans, 1)]
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as error:
        QuizService.validate_and_parse_quiz(json.dumps({"questions": questions}), question_count=2,
            source_metadata=sources, grounding_context=context, evidence_snapshot=evidence,
            answer_spans=QuizService._answer_span_snapshot(evidence))
    assert error.value.diagnostics["validated_count"] == 0
    assert error.value.diagnostics["requested_count"] == 2
    assert error.value.diagnostics["rejected_count"] == 2


def test_candidate_selection_binds_distinct_spans_before_generation():
    context = "[chapter-a]\nREST uses GET and POST methods.\n\n[chapter-b]\nProblemDetails describes API errors."
    sources = [{"source_id": "chapter-a"}, {"source_id": "chapter-b"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    candidates = QuizService._select_question_candidates(QuizService._answer_span_snapshot(evidence), 2)
    assert len(candidates) == 2
    assert len({candidate["answer_span_id"] for candidate in candidates}) == 2
    assert len({candidate["evidence_id"] for candidate in candidates}) == 2


def test_candidate_binding_rejects_a_valid_span_assigned_to_the_wrong_question():
    context = "[chapter-a]\nREST uses GET and POST methods."
    sources = [{"source_id": "chapter-a"}]
    evidence = QuizService._evidence_snapshot(context, sources)
    candidates = QuizService._select_question_candidates(QuizService._answer_span_snapshot(evidence), 2)
    assert len(candidates) == 2
    questions=[]
    for index, candidate in enumerate(reversed(candidates), 1):
        questions.append({
            "question": f"Câu hỏi candidate {index}?", "type": "mcq",
            "evidence_id": candidate["evidence_id"], "answer_span_id": candidate["answer_span_id"],
            "options": [{"id": "A", "text": candidate["text"]}, {"id": "B", "text": f"wrong-{index}-b"},
                        {"id": "C", "text": f"wrong-{index}-c"}, {"id": "D", "text": f"wrong-{index}-d"}],
            "correct_option_id": "A", "explanation": "Candidate binding fixture.",
        })
    with pytest.raises(ValueError, match="INVALID_QUIZ_SCHEMA") as error:
        QuizService.validate_and_parse_quiz(json.dumps({"questions": questions}), question_count=2,
            source_metadata=sources, grounding_context=context, evidence_snapshot=evidence,
            answer_spans=candidates, candidate_bindings=candidates)
    assert error.value.diagnostics["grounding_failure_reason"] == "answer_span_binding_mismatch"
    assert error.value.diagnostics["validated_count"] == 0
    assert error.value.diagnostics["rejected_count"] == 2


def test_existing_persisted_quiz_without_grounding_field_keeps_historical_grading():
    stored = [{
        "question_id": "historical-question", "question": "Historical question",
        "type": "mcq", "options": [
            {"id": "stored-correct", "text": "private correct text"},
            {"id": "stored-wrong", "text": "private wrong text"},
        ],
        "correct_option_id": "stored-correct", "explanation": "Historical rationale",
    }]
    result = GradingService().grade(stored, [{
        "question_id": "historical-question", "selected_option_id": "stored-wrong",
        "correct": True, "score": 100,
    }])
    assert result["score_percent"] == 0
    assert result["correct_count"] == 0
