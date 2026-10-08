from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(encoding="utf-8")


def test_student_course_detail_keeps_public_contracts_and_navigation():
    assert 'render_course_detail_hero(st, course_id' in SOURCE
    assert 'st.session_state.view_page = "courses"' in SOURCE
    assert 'f"/courses/{course_id}/materials"' in SOURCE
    assert '"/lms/chat"' in SOURCE
