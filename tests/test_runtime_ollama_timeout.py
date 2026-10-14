from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
LMS_APP = ROOT / "lms-dlu-demo"


def composed_timeout(configured: str | None) -> float:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(LMS_APP), environment.get("PYTHONPATH", "")]
    )
    if configured is None:
        environment.pop("OLLAMA_TIMEOUT_SECONDS", None)
    else:
        environment["OLLAMA_TIMEOUT_SECONDS"] = configured
    probe = (
        "import dotenv; "
        "dotenv.load_dotenv = lambda *args, **kwargs: False; "
        "import main; "
        "print(main._ollama_provider.timeout_seconds)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=LMS_APP,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    return float(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    ("configured", "expected"),
    [(None, 120.0), ("75", 75.0)],
)
def test_runtime_ollama_timeout_composition(configured, expected):
    assert composed_timeout(configured) == expected
