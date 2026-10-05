from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))

from ui.components import public_citation_titles


def test_public_citation_titles_deduplicates_in_retrieval_order():
    sources = [
        {"title": "3 - Ham.pdf"},
        {"title": "3 - Ham.pdf"},
        {"title": "lecture.docx"},
        {"title": "lecture.docx"},
        {"title": "final-demo-md.md"},
        {"title": "3 - Ham.pdf"},
    ]

    assert public_citation_titles(sources) == [
        "3 - Ham.pdf",
        "lecture.docx",
        "final-demo-md.md",
    ]
