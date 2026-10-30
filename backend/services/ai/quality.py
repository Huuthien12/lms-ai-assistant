import re
from typing import Any


_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_SOURCE = re.compile(r"\[\s*Nguồn\s*:?\s*#?\s*(\d+(?:\s*[,;]\s*\d+)*)\s*\]", re.IGNORECASE)
_INTERNAL_MARKER = re.compile(r"\b(?:reference_data|system_prompt|prompt_version)\b", re.IGNORECASE)


def evaluate_answer(status: str, raw_response: str, source_count: int) -> dict[str, Any]:
    citations = [int(value) for group in _SOURCE.findall(raw_response)
                 for value in re.split(r"\s*[,;]\s*", group)]
    if source_count == 0:
        citation_status = "not_required" if not citations else "invalid"
    elif not citations:
        citation_status = "missing"
    else:
        citation_status = "valid" if all(1 <= value <= source_count for value in citations) else "invalid"
    han_count = len(_HAN.findall(raw_response))
    letter_count = sum(character.isalpha() for character in raw_response)
    han_ratio = han_count / letter_count if letter_count else 0.0
    longest_han_run = max((len(value) for value in _HAN_RUN.findall(raw_response)), default=0)
    substantial_han = han_count >= 2 and (han_ratio >= 0.5 or longest_han_run >= 8)
    internal_marker_leak = bool(_INTERNAL_MARKER.search(raw_response))
    valid_citations = citation_status in {"valid", "not_required"}
    checks = {
        "provider_success": status == "success",
        "nonempty": bool(raw_response.strip()),
        "contains_han": han_count > 0,
        "han_character_count": han_count,
        "han_ratio": round(han_ratio, 4),
        "han_is_substantial": substantial_han,
        "citation_numbers": citations,
        "citation_status": citation_status,
        "citations_valid": valid_citations,
        "internal_marker_leak": internal_marker_leak,
    }
    checks["passed"] = (checks["provider_success"] and checks["nonempty"]
                        and not substantial_han and not internal_marker_leak and valid_citations)
    checks["quality_status"] = "passed" if checks["passed"] else "failed"
    if checks["passed"] and checks["contains_han"]:
        checks["quality_status"] = "warning"
    if not checks["provider_success"]:
        checks["display_action"] = "empty"
    elif not checks["nonempty"] or substantial_han or internal_marker_leak:
        checks["display_action"] = "fallback"
    else:
        checks["display_action"] = "raw"
    return checks


def displayed_answer(status: str, raw_response: str, evaluation: dict[str, Any]) -> str:
    if status != "success":
        return ""
    if evaluation["display_action"] == "fallback":
        return ("Tôi chưa thể tạo câu trả lời tiếng Việt đáng tin cậy từ các đoạn trích này. "
                "Vui lòng hỏi lại về một ý cụ thể trong tài liệu.")
    return raw_response
