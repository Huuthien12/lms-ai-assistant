from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/"lms-dlu-demo"))
from urllib.parse import urlsplit
import pytest
from streamlit.testing.v1 import AppTest
from deeptutor_client import RealDeepTutorClient, BackendRequestError
from verified_learning_ui import VerifiedSession, session_messages
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
    assert ui.selectbox[0].options==["INT1339"]
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
    ui.radio[0].set_value("A")
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
    ui.run()
    assert any("mastery_score" in m.value for m in ui.json)
    button(ui,"Đăng xuất").click().run()
    assert not ui.exception and len(ui.selectbox)==0
    with pytest.raises(KeyError): ui.session_state["verified_session"]
    with pytest.raises(KeyError): ui.session_state["work_quiz"]
    assert ui.text_input[0].value==""
    login(ui,"B")
    assert ui.selectbox[0].options==["OTHER"]
    assert not ui.session_state["work_messages"]


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



@pytest.mark.parametrize("url",["http://api.test:bad","http://[","http://user:password@api.test"])
def test_invalid_backend_origin_fails_closed(url,monkeypatch):
    monkeypatch.setattr("deeptutor_client.httpx.request",lambda *a,**k:pytest.fail("No HTTP for invalid origin"))
    with pytest.raises(BackendRequestError) as error: RealDeepTutorClient(url,personal_token="A").identity()
    assert error.value.status_code==503
