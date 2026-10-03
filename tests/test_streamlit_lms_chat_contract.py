from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(
    encoding="utf-8"
)


def test_streamlit_chat_uses_the_final_lms_contract():
    assert '"/lms/chat"' in SOURCE
    assert '"question": prompt' in SOURCE
    assert '"course_id": course_id' in SOURCE
    assert '"student_id":\n                        st.session_state.user_id' not in SOURCE


def test_streamlit_preserves_grounded_response_fields():
    assert 'response_data.get(\n                                "answer"' in SOURCE
    assert 'response_data.get("sources", [])' in SOURCE
    assert 'response_data.get("ai")' in SOURCE
