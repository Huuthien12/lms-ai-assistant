from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(encoding="utf-8")


def test_student_documents_uses_course_material_contract_without_paths():
    assert 'f"/courses/{course_id}/materials"' in SOURCE
    assert 'document_query' in SOURCE and 'document_format' in SOURCE
    assert 'material.get("file_path")' not in SOURCE
    assert 'URL công khai an toàn' in SOURCE


def test_student_documents_uses_modern_workspace_not_legacy_shell():
    assert 'render_workspace_header(' in SOURCE
    assert '<div class="dlu-black-nav">' not in SOURCE
