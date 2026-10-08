from pathlib import Path


SOURCE = (Path(__file__).resolve().parents[1] / "lms-dlu-demo" / "app.py").read_text(encoding="utf-8")


def test_lecturer_moodle_sync_uses_discovery_and_existing_ingestion_contract():
    assert 'api_get("/moodle/courses"' in SOURCE
    assert 'headers=MOODLE_DISCOVERY_HEADERS' in SOURCE
    assert '"X-Internal-Api-Key"' in SOURCE
    assert 'api_post("/moodle/resources/ingest"' in SOURCE
    assert '"/moodle/resources/ingest"' in SOURCE
    assert '"course_id_moodle": st.session_state.selected_moodle_course_id' in SOURCE


def test_lecturer_upload_forwards_the_internal_service_header_server_side():
    assert "files=files,\n                                timeout=120,\n                                headers=MOODLE_DISCOVERY_HEADERS," in SOURCE
    assert '"resource_id": resource["resource_id"]' in SOURCE
    assert "Create KB" not in SOURCE
    assert "generated Markdown" not in SOURCE


def test_roles_share_the_modern_sidebar_shell():
    assert 'with st.sidebar:' in SOURCE
    assert 'if role == "student":\n            st.markdown(' not in SOURCE
    assert 'key="sidebar_logout"' in SOURCE
