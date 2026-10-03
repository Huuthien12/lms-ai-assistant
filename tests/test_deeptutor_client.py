from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
from deeptutor_client import MockDeepTutorClient, RealDeepTutorClient, create_deeptutor_client


@pytest.mark.parametrize("value", ["true", "1", "yes"])
def test_factory_selects_mock_only_for_explicit_mock_values(monkeypatch, value):
    monkeypatch.setenv("USE_MOCK_API", value)
    client = create_deeptutor_client()

    assert isinstance(client, MockDeepTutorClient)
    assert client.ingest_resource(9, 1, "int1339-python")["status"] == "ready"
    chat = client.chat("Question", "INT1339", "int1339-python")
    assert chat["course_id"] == "INT1339"
    assert chat["kb_name"] == "int1339-python"
    assert set(chat["ai"]) == {"provider", "model", "fallback_used"}
    assert client.check_readiness()["status"] == "ready"


@pytest.mark.parametrize("value", [None, "false", "0", "no"])
def test_factory_selects_real_by_default_and_for_explicit_real_values(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("USE_MOCK_API", raising=False)
    else:
        monkeypatch.setenv("USE_MOCK_API", value)
    assert isinstance(create_deeptutor_client(), RealDeepTutorClient)


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


def test_real_client_maps_readiness_contract():
    response = MagicMock()
    response.json.return_value = {"status": "ready", "components": {}}
    with patch("deeptutor_client.httpx.get", return_value=response) as get:
        result = RealDeepTutorClient("http://api.test").check_readiness()
    assert result["status"] == "ready"
    assert get.call_args.args[0] == "http://api.test/health/ready"
    assert get.call_args.kwargs["timeout"] == 10


@pytest.mark.parametrize("payload", [{"status": "degraded", "components": {}}, {"status": "invalid"}, []])
def test_real_client_readiness_handles_degraded_and_invalid_payloads(payload):
    response = MagicMock()
    response.json.return_value = payload
    with patch("deeptutor_client.httpx.get", return_value=response):
        if isinstance(payload, dict) and payload.get("status") == "degraded":
            assert RealDeepTutorClient("http://api.test").check_readiness()["status"] == "degraded"
        else:
            with pytest.raises(RuntimeError, match="DeepTutor readiness is unavailable"):
                RealDeepTutorClient("http://api.test").check_readiness()


def test_real_client_readiness_sanitizes_timeout():
    with patch("deeptutor_client.httpx.get", side_effect=httpx.TimeoutException("secret")):
        with pytest.raises(RuntimeError, match="DeepTutor readiness is unavailable"):
            RealDeepTutorClient("http://api.test").check_readiness()
