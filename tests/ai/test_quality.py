from backend.services.ai.quality import displayed_answer, evaluate_answer


def test_vietnamese_answer_with_valid_citation_passes():
    raw = "Cấu trúc rẽ nhánh chọn phép toán phù hợp [Nguồn 1]."
    result = evaluate_answer("success", raw, 1)
    assert result["provider_success"] is True
    assert result["citation_status"] == "valid"
    assert result["quality_status"] == "passed" and result["passed"] is True
    assert displayed_answer("success", raw, result) == raw


def test_incidental_han_is_warning_without_rewriting_answer():
    raw = "Trong phép nhân, 乘以 là thuật ngữ có nghĩa là nhân [Nguồn: 1]."
    result = evaluate_answer("success", raw, 1)
    assert result["contains_han"] is True and result["han_character_count"] == 2
    assert result["han_is_substantial"] is False
    assert result["citations_valid"] is True
    assert result["quality_status"] == "warning" and result["display_action"] == "raw"
    assert displayed_answer("success", raw, result) == raw


def test_chinese_dominant_answer_uses_fallback_but_preserves_evaluation_input():
    raw = "这篇课文使用了递归的方法。[Nguồn 1]"
    result = evaluate_answer("success", raw, 1)
    assert result["han_is_substantial"] is True
    assert result["quality_status"] == "failed" and result["display_action"] == "fallback"
    assert raw not in displayed_answer("success", raw, result)


def test_missing_and_out_of_range_citations_have_distinct_results():
    missing = evaluate_answer("success", "Câu trả lời không có nguồn.", 2)
    invalid = evaluate_answer("success", "Câu trả lời [Nguồn #3].", 2)
    grouped = evaluate_answer("success", "Câu trả lời [Nguồn 1, 2].", 2)
    assert missing["citation_status"] == "missing" and missing["citation_numbers"] == []
    assert invalid["citation_status"] == "invalid" and invalid["citation_numbers"] == [3]
    assert grouped["citation_status"] == "valid" and grouped["citation_numbers"] == [1, 2]


def test_provider_failure_is_separate_from_answer_quality():
    result = evaluate_answer("error", "", 1)
    assert result["provider_success"] is False
    assert result["quality_status"] == "failed"
    assert result["display_action"] == "empty"
    assert displayed_answer("error", "", result) == ""


def test_empty_success_uses_safe_display_fallback():
    result = evaluate_answer("success", "  ", 1)
    assert result["provider_success"] is True and result["nonempty"] is False
    assert result["display_action"] == "fallback"
    assert displayed_answer("success", "  ", result)
