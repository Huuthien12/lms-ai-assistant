from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from deeptutor_client import MockDeepTutorClient, RealDeepTutorClient, create_deeptutor_client


def test_mock_client_matches_lms_response_shapes(monkeypatch):
    monkeypatch.setenv("USE_MOCK_API", "true")
    client = create_deeptutor_client()

    assert isinstance(client, MockDeepTutorClient)
    assert client.ingest_resource(9, 1, "int1339-python")["status"] == "ready"
    chat = client.chat("Question", "INT1339", "int1339-python")
    assert chat["course_id"] == "INT1339"
    assert chat["kb_name"] == "int1339-python"
    assert set(chat["ai"]) == {"provider", "model", "fallback_used"}


def test_real_client_maps_authoritative_ingestion_contract(monkeypatch):
    monkeypatch.setenv("USE_MOCK_API", "false")
    monkeypatch.setenv("DEEPTUTOR_API_BASE_URL", "http://api.test")
    response = MagicMock()
    response.json.return_value = {"status": "ready"}
    with patch("deeptutor_client.httpx.post", return_value=response) as post:
        create_deeptutor_client().ingest_resource(9, 1, "int1339-python")

    assert post.call_args.args[0] == "http://api.test/moodle/resources/ingest"
    assert post.call_args.kwargs["json"] == {"course_id_moodle": 9, "resource_id": 1, "kb_name": "int1339-python"}


def test_real_client_maps_authoritative_grounded_chat_contract():
    response = MagicMock()
    response.json.return_value = {"status": "success"}
    with patch("deeptutor_client.httpx.post", return_value=response) as post:
        RealDeepTutorClient("http://api.test").chat("Question", "INT1339", "int1339-python")

    assert post.call_args.args[0] == "http://api.test/chat/grounded"
    assert post.call_args.kwargs["json"] == {"question": "Question", "course_id": "INT1339", "kb_name": "int1339-python"}
