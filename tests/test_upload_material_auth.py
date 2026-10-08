import sys
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lms-dlu-demo"))
import main as lms_main


TOKEN = "test-upload-token"


def upload(client, headers=None):
    return client.post(
        "/upload-material/",
        data={"course_id": "INT1339"},
        files={"file": ("chapter.txt", b"chapter content", "text/plain")},
        headers=headers,
    )


def reject_upload_side_effects(monkeypatch):
    connection = MagicMock()
    monkeypatch.setattr(lms_main, "get_connection", connection)
    index = MagicMock()
    monkeypatch.setattr(lms_main, "index_document_to_deeptutor", index)
    return connection, index


def test_upload_material_rejects_missing_or_invalid_service_key_before_side_effects(monkeypatch):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN", TOKEN)
    connection, index = reject_upload_side_effects(monkeypatch)
    client = TestClient(lms_main.app)

    assert upload(client).status_code == 401
    assert upload(client, {"X-Internal-Api-Key": "wrong"}).status_code == 401
    connection.assert_not_called()
    index.assert_not_called()


def test_upload_material_fails_closed_when_service_auth_is_unconfigured(monkeypatch):
    monkeypatch.delenv("LMS_MOODLE_DISCOVERY_TOKEN", raising=False)
    connection, index = reject_upload_side_effects(monkeypatch)
    client = TestClient(lms_main.app)

    assert upload(client, {"X-Internal-Api-Key": TOKEN}).status_code == 503
    connection.assert_not_called()
    index.assert_not_called()


def test_upload_material_preserves_the_successful_multipart_contract(monkeypatch, tmp_path):
    monkeypatch.setenv("LMS_MOODLE_DISCOVERY_TOKEN", TOKEN)
    monkeypatch.setattr(lms_main, "UPLOAD_DIR", str(tmp_path))
    cursor = MagicMock()
    cursor.fetchone.side_effect = [("INT1339",), (41,)]
    connection = MagicMock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(lms_main, "get_connection", MagicMock(return_value=connection))
    index = MagicMock(return_value={"action": "add"})
    monkeypatch.setattr(lms_main, "index_document_to_deeptutor", index)
    client = TestClient(lms_main.app)

    response = upload(client, {"X-Internal-Api-Key": TOKEN})

    assert response.status_code == 200
    assert response.json()["material_id"] == 41
    assert response.json()["deeptutor"] == {"kb_name": "int1339-python", "indexed": True, "action": "add", "error": None}
    assert (tmp_path / "chapter.txt").read_bytes() == b"chapter content"
    connection.commit.assert_called_once()
    index.assert_called_once_with(course_id="INT1339", document_path=str(tmp_path / "chapter.txt"))
