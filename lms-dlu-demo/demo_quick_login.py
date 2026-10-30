"""Local-demo Moodle account profiles backed by per-user Windows DPAPI blobs."""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import shutil
import subprocess


_KEY = re.compile(r"^[a-z0-9_-]{1,32}$")
_FILE = re.compile(r"^[a-z0-9_-]{1,64}\.dpapi$")
_DEFAULT = "student-a|Sinh viên A|student-a.dpapi;student-b|Sinh viên B|student-b.dpapi;teacher-l|Giảng viên L|teacher-l.dpapi"


class DemoSecretUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoAccount:
    key: str
    label: str
    secret_file: str


def quick_login_enabled() -> bool:
    return os.getenv("DEMO_QUICK_LOGIN_ENABLED", "false").strip().lower() in {"1", "true", "yes"}


def configured_accounts() -> list[DemoAccount]:
    if not quick_login_enabled():
        return []
    accounts=[]
    seen=set()
    for entry in os.getenv("DEMO_QUICK_LOGIN_ACCOUNTS", _DEFAULT).split(";"):
        fields=[field.strip() for field in entry.split("|")]
        if (len(fields)!=3 or not _KEY.fullmatch(fields[0]) or not fields[1]
                or not _FILE.fullmatch(fields[2]) or fields[0] in seen):
            continue
        seen.add(fields[0]); accounts.append(DemoAccount(*fields))
    return accounts


def load_account_token(account: DemoAccount) -> str:
    """Read a current-Windows-user DPAPI blob without logging or exposing its value."""
    default_root=os.getenv("LOCALAPPDATA")
    configured_root=os.getenv("DEMO_DPAPI_SECRET_DIR")
    if not configured_root and not default_root:
        raise DemoSecretUnavailable()
    root=Path(configured_root) if configured_root else Path(default_root) / "DeepTutor" / "demo-accounts"
    path=(root / account.secret_file).resolve()
    if path.parent != root.resolve() or not path.is_file():
        raise DemoSecretUnavailable()
    powershell=shutil.which("powershell.exe") or shutil.which("powershell")
    helper=Path(__file__).with_name("demo_dpapi_secret_loader.ps1")
    if not powershell or not helper.is_file():
        raise DemoSecretUnavailable()
    try:
        result=subprocess.run([powershell,"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(helper),"-SecretPath",str(path)],
                              capture_output=True,text=True,timeout=3,check=False)
    except (OSError,subprocess.SubprocessError):
        raise DemoSecretUnavailable() from None
    token=result.stdout.strip() if result.returncode==0 else ""
    if not token:
        raise DemoSecretUnavailable()
    return token
