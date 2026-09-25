from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class DeepTutorConfig:
    repository_root: Path
    deeptutor_dir: Path
    executable: Path
    runtime_dir: Path
    command_timeout_seconds: int = 300

    @classmethod
    def from_env(cls, repository_root: Path | None = None) -> "DeepTutorConfig":
        root = (repository_root or Path(__file__).resolve().parents[1]).resolve()
        deeptutor_dir = Path(os.getenv("DEEPTUTOR_DIR", root / "DeepTutor")).resolve()
        default_executable = deeptutor_dir / ".venv" / (
            "Scripts/deeptutor.exe" if os.name == "nt" else "bin/deeptutor"
        )
        executable = Path(os.getenv("DEEPTUTOR_EXE", default_executable)).resolve()
        runtime_dir = Path(
            os.getenv("DEEPTUTOR_RUNTIME_DIR", root / ".deeptutor-runtime")
        ).resolve()
        timeout = int(os.getenv("DEEPTUTOR_TIMEOUT_SECONDS", "300"))
        if timeout <= 0:
            raise ValueError("DEEPTUTOR_TIMEOUT_SECONDS must be positive")
        return cls(root, deeptutor_dir, executable, runtime_dir, timeout)
