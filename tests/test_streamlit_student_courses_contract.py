from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(encoding="utf-8")


def test_student_courses_stops_before_legacy_shell():
    courses = SOURCE.index('if role == "student" and st.session_state.view_page == "courses":')
    assert 'render_student_courses_hero(st, len(courses_data))' in SOURCE[courses:]
    assert 'TRƯỜNG ĐẠI HỌC ĐÀ LẠT' not in SOURCE
    assert '<div class="dlu-black-nav">' not in SOURCE


def test_student_courses_uses_api_data_and_preserves_navigation():
    assert 'api_get("/courses", timeout=15)' in SOURCE
    assert 'st.session_state.view_page = "course_detail"' in SOURCE
    assert 'student_courses_query' in SOURCE
    assert 'student_courses_sort' in SOURCE
