"""Adapter over DeepTutor's persisted full raw nodes; no alternate RAG engine."""
import json
import os
from pathlib import Path
import subprocess
from typing import Protocol
from .adapter import CliDeepTutorAdapter
from .errors import DeepTutorError


class FullSourceAdapter(Protocol):
    def publish(self, physical_kb: str, path: Path) -> dict: ...
    def retrieve(self, physical_kb: str, question: str, timeout_seconds: float | None = None) -> dict: ...


class DeepTutorFullSourceAdapter:
    def __init__(self, config):
        self.config=config
        self.cli=CliDeepTutorAdapter(config)

    def _raw(self, operation, physical_kb, question="", timeout_seconds=None):
        if not self.config.python_executable.is_file():
            raise DeepTutorError("raw_runtime_unavailable","Full-source runtime is unavailable.",status_code=503)
        worker=Path(__file__).with_name("full_source_worker.py")
        environment=os.environ.copy()
        environment.update(PYTHONUTF8="1",PYTHONIOENCODING="utf-8",PYTHONDONTWRITEBYTECODE="1")
        # The bridge imports the existing engine from its own checkout/venv.
        environment["PYTHONPATH"]=str(self.config.deeptutor_dir)
        try:
            timeout=self.config.command_timeout_seconds if timeout_seconds is None else timeout_seconds
            if timeout <= 0: raise subprocess.TimeoutExpired("deeptutor",timeout)
            result=subprocess.run([str(self.config.python_executable),str(worker),operation,physical_kb,question],
                cwd=self.config.deeptutor_dir,env=environment,stdin=subprocess.DEVNULL,
                capture_output=True,text=True,encoding="utf-8",timeout=timeout,
                shell=False,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
            data=json.loads(result.stdout)
            if result.returncode or not isinstance(data,dict): raise ValueError()
        except subprocess.TimeoutExpired:
            raise DeepTutorError("retrieval_timeout","Verified retrieval timed out.",status_code=504) from None
        except (OSError,ValueError,subprocess.SubprocessError):
            raise DeepTutorError("raw_retrieval_unavailable","Full-source runtime is unavailable.",status_code=502) from None
        if data.get("needs_reindex"):
            raise DeepTutorError("kb_not_ready","Publication requires indexing.",status_code=409)
        if data.get("error"):
            status=data.get("status_code")
            raise DeepTutorError("raw_retrieval_unavailable","Full-source runtime is unavailable.",
                                status_code=status if status in (409,502,503) else 502)
        return data

    def publish(self, physical_kb, path):
        # Each document version gets an immutable private engine KB. No partial update
        # can modify an index serving a previously ACTIVE publication.
        if self.cli.get_knowledge_base(physical_kb) is not None:
            raise DeepTutorError("publication_conflict","Publication already exists.",status_code=409)
        self.cli.create_knowledge_base(physical_kb,path)
        return self._raw("manifest",physical_kb)

    def retrieve(self, physical_kb, question, timeout_seconds=None):
        return self._raw("search",physical_kb,question,timeout_seconds)
