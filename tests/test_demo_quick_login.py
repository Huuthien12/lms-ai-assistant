from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parents[1] / "lms-dlu-demo"))
import demo_quick_login as quick


def test_quick_login_is_disabled_without_explicit_operator_configuration(monkeypatch):
    monkeypatch.delenv("DEMO_QUICK_LOGIN_ENABLED", raising=False)
    assert quick.configured_accounts() == []


def test_quick_login_reads_only_a_configured_dpapi_blob(monkeypatch, tmp_path):
    secret = tmp_path / "student-a.dpapi"; secret.write_text("protected", encoding="utf-8")
    monkeypatch.setenv("DEMO_QUICK_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_DPAPI_SECRET_DIR", str(tmp_path))
    monkeypatch.setattr(quick.shutil, "which", lambda _: "powershell.exe")
    monkeypatch.setattr(quick.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="token-not-rendered\n"))
    account=quick.configured_accounts()[0]
    assert [item.key for item in quick.configured_accounts()] == ["student-a", "student-b", "teacher-l"]
    assert quick.load_account_token(account) == "token-not-rendered"


def test_quick_login_missing_secret_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_QUICK_LOGIN_ENABLED", "true")
    monkeypatch.setenv("DEMO_DPAPI_SECRET_DIR", str(tmp_path))
    account=quick.configured_accounts()[0]
    try:
        quick.load_account_token(account)
    except quick.DemoSecretUnavailable:
        pass
    else:
        raise AssertionError("missing DPAPI blob must not create a demo credential")
