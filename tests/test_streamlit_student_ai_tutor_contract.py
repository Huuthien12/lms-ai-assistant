from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(encoding="utf-8")


def test_ai_tutor_reuses_materials_and_grounded_chat_contracts():
    assert 'related_materials = materials_result["data"].get("materials", [])' in SOURCE
    assert 'render_document_row(st, material)' in SOURCE
    assert '"/lms/chat"' in SOURCE
    assert 'render_citations(st, response_data.get("sources", []))' in SOURCE
