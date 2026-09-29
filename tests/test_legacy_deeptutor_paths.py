from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
import main as lms_main


def test_legacy_kb_name_uses_the_centralized_mapping():
    assert lms_main.get_kb_name("INT1339") == "int1339-python"


def test_legacy_local_upload_bridge_delegates_to_deeptutor_service(tmp_path, monkeypatch):
    document = tmp_path / "chapter.pdf"
    document.write_bytes(b"%PDF")
    service = MagicMock()
    service.ingest_document.return_value = {"kb_id": "int1339-python", "action": "add"}
    monkeypatch.setattr(lms_main, "DEEPTUTOR_SERVICE", service)

    result = lms_main.index_document_to_deeptutor("INT1339", str(document))

    assert result == {"kb_id": "int1339-python", "action": "add"}
    request = service.ingest_document.call_args.args[0]
    assert (request.course_id, request.filename, request.path) == ("INT1339", "chapter.pdf", str(document))


def test_legacy_status_hides_runtime_errors(monkeypatch):
    service = MagicMock()
    service.health.side_effect = RuntimeError("D:/private/token=secret")
    monkeypatch.setattr(lms_main, "DEEPTUTOR_SERVICE", service)

    response = lms_main.deeptutor_status()

    assert response == {"available": False, "command_success": False}
    assert "private" not in str(response).lower()
    assert "secret" not in str(response).lower()


def test_legacy_chat_hides_source_paths(monkeypatch):
    service = MagicMock()
    service.query.return_value = {
        "kb_id": "int1339-python",
        "result": {"answer": "Grounded answer", "sources": [{
            "title": "chapter.pdf", "page": 1, "score": 0.9, "source": "D:/private/staging.pdf",
        }]},
    }
    monkeypatch.setattr(lms_main, "DEEPTUTOR_SERVICE", service)

    response = lms_main.ask_deeptutor("INT1339", "Question")

    assert response["sources"] == [{"title": "chapter.pdf", "page": 1, "score": 0.9}]
    assert "private" not in str(response).lower()
