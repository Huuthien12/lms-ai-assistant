from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"lms-dlu-demo"))
from urllib.parse import urlsplit
import httpx
import pytest
from streamlit.testing.v1 import AppTest
from deeptutor_client import RealDeepTutorClient, BackendRequestError
from verified_learning_ui import (VerifiedSession, display_quiz_text, progress_label, progress_percent,
                                  progress_updated_at, session_messages)
from ui.components import course_display_name, quiz_document_titles
from test_verified_learning_integration import learning, runtime


@pytest.fixture
def ui(learning,monkeypatch):
    backend,*_=learning
    def transport(method,url,**kwargs):
        assert kwargs["follow_redirects"] is False
        assert set(kwargs["headers"])=={"Authorization"}
        assert "X-Internal-Api-Key" not in kwargs["headers"]
        assert "token" not in url.lower()
        return backend.request(method,urlsplit(url).path,headers=kwargs["headers"],json=kwargs.get("json"))
    monkeypatch.setattr("deeptutor_client.httpx.request",transport)
    app=AppTest.from_file(str(Path(__file__).parents[1]/"lms-dlu-demo"/"app.py"),default_timeout=30).run()
    assert not app.exception
    return app


def button(app,label): return next(b for b in app.button if b.label==label)


def login(app,user="A"):
    app.text_input[0].set_value(user)
    button(app,"Đăng nhập").click().run()
    assert not app.exception


def test_authenticated_streamlit_chat_quiz_grade_progress_and_logout(ui):
    assert len(ui.selectbox)==0
    login(ui)
    assert next(item for item in ui.selectbox if item.label=="Khóa học của tôi").options==["Lập trình Python"]
    assert ui.session_state["verified_course"]=="INT1339"
    assert [radio.label for radio in ui.radio].count("Phạm vi kiến thức")==2
    assert any(select.label=="Chọn chương" for select in ui.selectbox)
    ui.chat_input[0].set_value("Explain Python").run()
    assert not ui.exception
    sources=ui.session_state["work_messages"][-1]["sources"]
    assert sources and sources[0]["verification_status"]=="VERIFIED_ACTIVE"
    ui.run()
    assert ui.session_state["work_messages"][-1]["sources"]==sources
    ui.number_input[0].set_value(1)
    button(ui,"Tạo Quiz").click().run()
    assert not ui.exception
    assert "correct_option_id" not in str(ui.session_state["work_quiz"])
    question=ui.session_state["work_quiz"]["questions"][0]
    quiz_radio=next(radio for radio in ui.radio if radio.label==display_quiz_text(question["question"]))
    assert quiz_radio.value is None
    assert list(quiz_radio.options)==[display_quiz_text(option["text"]) for option in question["options"]]
    option_id=question["options"][0]["id"]
    quiz_radio.set_value(option_id)
    button(ui,"Nộp bài").click().run()
    assert not ui.exception
    assert ui.session_state["work_grade"]["score_percent"]==100
    assert any(m.label=="Điểm từ server" and str(m.value) in {"100.0","100"} for m in ui.metric)
    button(ui,"Xem giải thích").click().run()
    assert not ui.exception and ui.session_state["work_review"]["results"][0]["explanation_status"]=="available"
    ui.number_input[1].set_value(1)
    button(ui,"Tạo Flashcards").click().run()
    assert not ui.exception and any(e.label=="Python?" for e in ui.expander)
    button(ui,"Ghi nhận ôn tập").click().run()
    assert not ui.exception and ui.success
    next(radio for radio in ui.radio if radio.label=="Hiển thị").set_value("Đã ôn").run()
    assert any(e.label=="Python?" for e in ui.expander)
    ui.run()
    assert not ui.json
    assert any(m.label=="Mức độ thành thạo" for m in ui.metric)
    assert any("Gợi ý ôn tập" in item.value for item in ui.info)
    assert any("Dùng các tab Quiz hoặc Flashcards" in item.value for item in ui.caption)
    button(ui,"Đăng xuất").click().run()
    assert not ui.exception and len(ui.selectbox)==0
    with pytest.raises(KeyError): ui.session_state["verified_session"]
    with pytest.raises(KeyError): ui.session_state["work_quiz"]
    assert ui.text_input[0].value==""
    login(ui,"B")
    assert next(item for item in ui.selectbox if item.label=="Khóa học của tôi").options==["Khóa học"]
    assert ui.session_state["verified_course"]=="OTHER"
    assert not ui.session_state["work_messages"]


def test_streamlit_post_quiz_flashcard_review_action(ui):
    login(ui)
    ui.number_input[0].set_value(1)
    button(ui,"Tạo Quiz").click().run()
    question=ui.session_state["work_quiz"]["questions"][0]
    quiz_radio=next(radio for radio in ui.radio if radio.label==display_quiz_text(question["question"]))
    quiz_radio.set_value(question["options"][1]["id"])
    button(ui,"Nộp bài").click().run()
    assert ui.session_state["work_grade"]["score_percent"]==0
    button(ui,"Ôn tập câu sai bằng Flashcard").click().run()
    assert not ui.exception and ui.session_state["work_review_batch"]["status"]=="READY"


def test_quiz_and_flashcard_number_inputs_stay_within_limits(ui):
    login(ui)
    assert ui.number_input[0].value==3 and ui.number_input[1].value==3
    assert not any(item.key in {"quiz_count_plus", "quiz_count_minus", "card_count_plus", "card_count_minus"}
                   for item in ui.button)
    ui.number_input[0].set_value(1).run()
    ui.number_input[1].set_value(20).run()
    assert ui.session_state["quiz_count"]==1 and ui.session_state["card_count"]==20


@pytest.mark.parametrize(("score", "expected"), [(40, 40), (-1, 0), (150, 100), (None, None)])
def test_progress_dashboard_mappings_are_learner_facing(score, expected):
    assert progress_percent(score) == expected
    assert progress_label({"WEAK": "Cần ôn tập"}, "WEAK") == "Cần ôn tập"
    assert progress_label({"WEAK": "Cần ôn tập"}, "UNKNOWN") == "Chưa có dữ liệu"
    assert progress_updated_at("2026-10-22T01:09:59.978805") == "22/10/2026 01:09"
    assert progress_updated_at("not-a-date") == "Chưa có dữ liệu"


def test_quiz_formula_display_preserves_factorial_and_multiplication():
    assert display_quiz_text("n!=1*2*3*...*n") == "n! = 1 × 2 × 3 × ... × n"
    assert display_quiz_text("a * b") == r"a \* b"


def test_quiz_document_titles_are_per_document_and_use_a_safe_legacy_fallback():
    sources = [
        {"document_id": "doc-a", "title": "Chuong 1.pdf", "chunk_id": "one"},
        {"document_id": "doc-a", "title": "Chuong 1.pdf", "chunk_id": "two"},
        {"publication_ref": "publication-b", "title": "Chuong 2.pdf", "chunk_id": "three"},
        {"title": "Quiz cu.pdf", "chunk_id": "four"},
        {"title": "Quiz cu.pdf", "chunk_id": "five"},
        {"document_id": "other-course", "title": "Khong duoc truyen tu backend.pdf"},
    ]
    assert quiz_document_titles(sources[:-1]) == ["Chuong 1.pdf", "Chuong 2.pdf", "Quiz cu.pdf"]
    # Cross-course data is never mixed into the per-question source list by the router.
    assert quiz_document_titles(sources[:1]) == ["Chuong 1.pdf"]


def test_course_display_names_are_presentation_only():
    assert course_display_name("INT1339") == "Lập trình Python"
    assert course_display_name("INT2001") == "Lập trình Web nâng cao"
    assert course_display_name("OTHER", "Môn Moodle xác minh") == "Môn Moodle xác minh"
    assert course_display_name("OTHER") == "Khóa học"


def test_invalid_login_has_no_course_or_authenticated_session(ui):
    ui.text_input[0].set_value("invalid")
    button(ui,"Đăng nhập").click().run()
    assert not ui.exception and ui.error and len(ui.selectbox)==0
    with pytest.raises(KeyError): ui.session_state["verified_session"]


def test_credential_repr_and_message_citation_snapshot():
    session=VerifiedSession("secret-fixture-token",{"owner_ref":"owner"})
    assert "secret-fixture-token" not in repr(session)
    sources=[{"document_id":"D","source_ref":"ref","title":"lecture.pdf"}]
    messages=session_messages([{"question":"Question","response":{"status":"success","answer":"Answer","sources":sources,"context_id":"context"}}])
    assert messages[-1]["sources"]==sources and messages[-1]["context_id"]=="context"


def test_personal_client_requires_credential_before_network(monkeypatch):
    def forbidden(*args,**kwargs): raise AssertionError("Must not call backend")
    monkeypatch.setattr("deeptutor_client.httpx.request",forbidden)
    with pytest.raises(BackendRequestError) as error: RealDeepTutorClient("http://api.test").identity()
    assert error.value.status_code==401


def test_client_preserves_safe_backend_code_and_timeout(monkeypatch):
    class Response:
        status_code=504
        def json(self): return {"detail":{"code":"LEARNING_GENERATION_TIMEOUT","debug":"secret"}}
    monkeypatch.setattr("deeptutor_client.httpx.request",lambda *a,**k:Response())
    with pytest.raises(BackendRequestError) as error:
        RealDeepTutorClient("http://api.test",personal_token="A").request("POST","/learning")
    assert (error.value.status_code,error.value.code)==(504,"LEARNING_GENERATION_TIMEOUT")
    monkeypatch.setattr("deeptutor_client.httpx.request",
                        lambda *a,**k:(_ for _ in ()).throw(httpx.ReadTimeout("secret")))
    with pytest.raises(BackendRequestError) as error:
        RealDeepTutorClient("http://api.test",personal_token="A").request("POST","/learning")
    assert (error.value.status_code,error.value.code)==(504,"CLIENT_TIMEOUT")
    assert "secret" not in str(error.value)


def test_client_preserves_provider_request_too_large_status(monkeypatch):
    class Response:
        status_code=413
        def json(self): return {"detail":{"code":"LEARNING_PROVIDER_REQUEST_TOO_LARGE","debug":"secret"}}
    monkeypatch.setattr("deeptutor_client.httpx.request",lambda *a,**k:Response())
    with pytest.raises(BackendRequestError) as error:
        RealDeepTutorClient("http://api.test",personal_token="A").request("POST","/learning")
    assert (error.value.status_code,error.value.code)==(413,"LEARNING_PROVIDER_REQUEST_TOO_LARGE")
    assert "secret" not in str(error.value)



@pytest.mark.parametrize("url",["http://api.test:bad","http://[","http://user:password@api.test"])
def test_invalid_backend_origin_fails_closed(url,monkeypatch):
    monkeypatch.setattr("deeptutor_client.httpx.request",lambda *a,**k:pytest.fail("No HTTP for invalid origin"))
    with pytest.raises(BackendRequestError) as error: RealDeepTutorClient(url,personal_token="A").identity()
    assert error.value.status_code==503
