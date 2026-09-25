from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Protocol

from .config import DeepTutorConfig
from .errors import DeepTutorError


class DeepTutorAdapter(Protocol):
    def health(self) -> dict[str, Any]: ...
    def list_knowledge_bases(self) -> list[dict[str, Any]]: ...
    def get_knowledge_base(self, kb_id: str) -> dict[str, Any] | None: ...
    def create_knowledge_base(self, kb_id: str, document_path: Path) -> None: ...
    def add_document(self, kb_id: str, document_path: Path) -> None: ...
    def search(self, kb_id: str, question: str) -> dict[str, Any]: ...


@dataclass
class CliDeepTutorAdapter:
    config: DeepTutorConfig

    def _run(self, args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        if not self.config.deeptutor_dir.is_dir() or not self.config.executable.is_file():
            raise DeepTutorError(
                "runtime_unavailable",
                "DeepTutor runtime is not available.",
                status_code=503,
            )
        env = os.environ.copy()
        env.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "TERM": "dumb", "NO_COLOR": "1"})
        try:
            result = subprocess.run(
                [str(self.config.executable), *args],
                cwd=self.config.deeptutor_dir,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                timeout=timeout or self.config.command_timeout_seconds,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            raise DeepTutorError("timeout", "DeepTutor command timed out.", status_code=504) from exc
        except OSError as exc:
            raise DeepTutorError("runtime_unavailable", "DeepTutor could not be started.", status_code=503) from exc
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or "DeepTutor command failed."
            raise DeepTutorError(
                "process_failure",
                "DeepTutor command failed.",
                status_code=502,
                details={"reason": message[:1000]},
            )
        return result

    @staticmethod
    def _json(stdout: str, code: str) -> Any:
        try:
            return json.loads(stdout.strip())
        except (json.JSONDecodeError, TypeError) as exc:
            raise DeepTutorError(code, "DeepTutor returned an invalid response.", status_code=502) from exc

    def health(self) -> dict[str, Any]:
        available = self.config.deeptutor_dir.is_dir() and self.config.executable.is_file()
        return {"available": available, "status": "available" if available else "unavailable"}

    def list_knowledge_bases(self) -> list[dict[str, Any]]:
        return self._json(self._run(["kb", "list", "--format", "json"], 60).stdout, "invalid_status")

    def get_knowledge_base(self, kb_id: str) -> dict[str, Any] | None:
        knowledge_bases = self.list_knowledge_bases()
        names = {
            str(item.get("name") or item.get("id") or item.get("kb_id"))
            for item in knowledge_bases
            if isinstance(item, dict)
        }
        if kb_id not in names:
            return None
        result = self._run(["kb", "info", kb_id], 60)
        return self._json(result.stdout, "invalid_status")

    def create_knowledge_base(self, kb_id: str, document_path: Path) -> None:
        self._run(["kb", "create", kb_id, "--doc", str(document_path)])

    def add_document(self, kb_id: str, document_path: Path) -> None:
        self._run(["kb", "add", kb_id, "--doc", str(document_path)])

    def search(self, kb_id: str, question: str) -> dict[str, Any]:
        result = self._run(["kb", "search", kb_id, question, "--format", "json"])
        return self._json(result.stdout, "invalid_query_response")
