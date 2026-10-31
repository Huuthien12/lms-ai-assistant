from pathlib import Path


LAUNCHER = Path(__file__).parents[1] / "lms-dlu-demo" / "start_lms.bat"


def test_demo_launcher_keeps_quick_login_local_and_secret_free():
    launcher = LAUNCHER.read_text(encoding="utf-8")

    assert 'set "DEMO_QUICK_LOGIN_ENABLED=true"' in launcher
    assert 'uvicorn main:app --host 127.0.0.1 --port 8001' in launcher
    assert 'streamlit run app.py --server.address 127.0.0.1 --server.port 8502' in launcher
    assert "MOODLE_TOKEN=" not in launcher
    assert "MOODLE_PASSWORD=" not in launcher
    assert "GROQ_API_KEY=" not in launcher
