"""Conservative display cleanup; never use this text to verify indexed hashes."""
import re


def contains_prompt_override(text: str) -> bool:
    # shortcut: catch explicit overrides, not every paraphrase; use a stronger model for adversarial documents.
    return bool(re.search(
        r"system\s+override|<\|(?:im_start|start_header_id)\|>\s*system"
        r"|(?:ignore|disregard|forget)\s+(?:(?:all|any|the)\s+)?(?:user|previous|prior|system|above)\b"
        r"|(?:answer|respond|reply)\s+(?:only\s+)?in\s+(?:chinese|mandarin)\b"
        r"|bỏ qua\s+(?:(?:mọi|các|tất cả)\s+)?(?:chỉ dẫn|hướng dẫn|quy tắc|yêu cầu)"
        r"|(?:chỉ\s+)?trả lời\s+bằng\s+tiếng\s+trung"
        r"|忽略.{0,20}(?:指令|规则)", text, re.IGNORECASE))


def clean_context_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned = []
    fence = None
    math_block = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        marker = re.match(r"^(`{3,}|~{3,})", stripped)
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            cleaned.append(line)
            continue
        if fence is not None:
            cleaned.append(line)
            continue
        if stripped in ("$$", r"\[", r"\]"):
            math_block = not math_block
            cleaned.append(line)
            continue
        if math_block:
            cleaned.append(line)
            continue
        # Missing PDF glyphs cannot be reconstructed safely (they may be operators).
        parts = re.split(r"(`+[^`]*`+|\$[^$]+\$|\\\(.*?\\\))", line)
        line = "".join(part if i % 2 else re.sub(r"\(cid:\d+\)", "�", part)
                       for i, part in enumerate(parts))
        if re.fullmatch(r"[\s|]+", line) and "|" in line:
            continue
        if re.fullmatch(r"\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*", line):
            # Keep real Markdown table headers; drop only orphan separators.
            if not cleaned or "|" not in cleaned[-1] or not cleaned[-1].strip(" |\t"):
                continue
            cells = cleaned[-1].strip().strip("|").split("|")
            if (sum(not cell.strip() for cell in cells) >= len(cells) / 2
                    and (index + 1 == len(lines) or "|" not in lines[index + 1])):
                # A sparse header with no data rows is a PDF layout artifact.
                cleaned[-1] = " ".join(cell.strip() for cell in cells if cell.strip())
                continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()
