from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))

from ui.components import public_citation_titles, render_citations, strip_system_citation_markers


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


def test_render_citations_shows_one_deduplicated_document_line_without_metadata():
    class Streamlit:
        def __init__(self): self.lines=[]
        def markdown(self, value, **_): self.lines.append(value)
    st = Streamlit()
    render_citations(st, [
        {"document_id":"d1","document_version_id":"v1","chunk_id":"secret-1","title":"Chương 3.pdf"},
        {"document_id":"d1","document_version_id":"v1","chunk_id":"secret-2","title":"Chương 3.pdf"},
        {"document_id":"d2","document_version_id":"v2","chunk_id":"secret-3","title":"Chương 2.pdf","page":7},
    ])
    rendered="\n".join(st.lines)
    assert rendered.count("Chương 3.pdf") == 1
    assert rendered.count("Tài liệu tham khảo:") == 1
    assert "Nguồn" not in rendered and "Trang/slide" not in rendered
    assert "secret-" not in rendered and "document_id" not in rendered and "v1" not in rendered


def test_strip_system_citation_markers_uses_only_valid_source_indexes():
    sources=[{"title":"Chương 1.pdf"},{"title":"Chương 2.pdf"}]
    assert strip_system_citation_markers("Đáp án đúng [Nguồn 1]. Xem thêm [Nguồn 1, Nguồn 2] và [1].", sources) == "Đáp án đúng. Xem thêm và."
    assert strip_system_citation_markers("Danh sách [3] và biểu thức [x].", sources) == "Danh sách [3] và biểu thức [x]."


def test_render_citations_does_not_invent_a_document_for_empty_or_invalid_sources():
    class Streamlit:
        def __init__(self): self.lines=[]
        def markdown(self, value, **_): self.lines.append(value)
    st = Streamlit()
    render_citations(st, [{"title":""}, {"chunk_id":"internal-only"}])
    assert st.lines == []
