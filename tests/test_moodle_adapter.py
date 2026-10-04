import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Cho phép import MoodleAdapter từ thư mục lms-dlu-demo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lms-dlu-demo')))
from moodle_adapter import MoodleAdapter

class TestMoodleAdapter(unittest.TestCase):
    def setUp(self):
        self.fake_token = "secret_mock_token_123"
        self.adapter = MoodleAdapter(base_url="https://fake-moodle.edu.vn", token=self.fake_token)

    @patch("moodle_adapter.requests.get")
    def test_success_normalization(self, mock_get):
        # Thiết lập mock responses
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9, "shortname": "INT1339", "fullname": "Kiến trúc máy tính"}]

        resource_resp = MagicMock()
        resource_resp.json.return_value = {
            "resources": [
                {
                    "id": 1,
                    "contentfiles": [
                        {
                            "filename": "Chuong1.pdf",
                            "mimetype": "application/pdf",
                            "fileurl": "https://fake-moodle.edu.vn/file.pdf"
                        }
                    ]
                }
            ]
        }

        pdf_resp = MagicMock()
        pdf_resp.content = b"%PDF-1.4 FAKE PDF CONTENT"
        pdf_resp.headers = {"Content-Type": "application/pdf"}

        mock_get.side_effect = [course_resp, resource_resp, pdf_resp]

        doc, pdf_bytes = self.adapter.get_normalized_document(course_id_moodle=9, resource_id=1)

        # 1 & 2. Kiểm tra normalization thành công và fields chuẩn
        self.assertEqual(doc["course_id"], "INT1339")
        self.assertEqual(doc["document_id"], "1")
        self.assertEqual(doc["filename"], "Chuong1.pdf")
        self.assertEqual(doc["mime_type"], "application/pdf")
        self.assertEqual(doc["source"], "moodle")

        # 3. PDF bytes được trả riêng
        self.assertEqual(pdf_bytes, b"%PDF-1.4 FAKE PDF CONTENT")
        self.assertEqual(mock_get.call_args_list[2].kwargs["params"], {"token": self.fake_token})
        self.assertEqual(mock_get.call_args_list[2].kwargs["timeout"], 30)

        # 4 & 5. Không lộ token và không lưu URL/path
        self.assertNotIn("path", doc)
        doc_str = str(doc)
        self.assertNotIn(self.fake_token, doc_str)
        self.assertNotIn("token=", doc_str)
        self.assertNotIn("https://fake-moodle", doc_str)

    @patch("moodle_adapter.requests.get")
    def test_missing_resource(self, mock_get):
        # 6. Resource không tồn tại
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9}]

        resource_resp = MagicMock()
        resource_resp.json.return_value = {"resources": []}

        mock_get.side_effect = [course_resp, resource_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_normalized_document(9, 999)
        self.assertIn("Không tìm thấy tài liệu", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_empty_contentfiles(self, mock_get):
        # 7. Contentfiles thiếu/rỗng
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9}]

        resource_resp = MagicMock()
        resource_resp.json.return_value = {
            "resources": [{"id": 1, "contentfiles": []}]
        }

        mock_get.side_effect = [course_resp, resource_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_normalized_document(9, 1)
        self.assertIn("rỗng/thiếu", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_moodle_ws_error_json(self, mock_get):
        # 8. Moodle Web Service trả lỗi
        err_resp = MagicMock()
        err_resp.json.return_value = {
            "exception": "moodle_exception",
            "errorcode": "invalidtoken",
            "message": "Token không hợp lệ"
        }
        mock_get.return_value = err_resp

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_normalized_document(9, 1)
        self.assertIn("Moodle Web Service error", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_pdf_download_http_failure(self, mock_get):
        # 9. PDF download HTTP failure
        import requests
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9}]

        resource_resp = MagicMock()
        resource_resp.json.return_value = {
            "resources": [{"id": 1, "contentfiles": [{"fileurl": "https://fake.com/file"}]}]
        }

        pdf_resp = MagicMock()
        pdf_resp.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")

        mock_get.side_effect = [course_resp, resource_resp, pdf_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_normalized_document(9, 1)
        self.assertIn("Lỗi HTTP khi tải file PDF", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_rejects_non_pdf_download(self, mock_get):
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9, "shortname": "INT1339"}]
        resource_resp = MagicMock()
        resource_resp.json.return_value = {"resources": [{"id": 1, "contentfiles": [{
            "filename": "chapter.pdf", "mimetype": "application/pdf", "fileurl": "https://fake.com/file"
        }]}]}
        downloaded = MagicMock()
        downloaded.content = b"<html>login</html>"
        downloaded.headers = {"Content-Type": "text/html"}
        mock_get.side_effect = [course_resp, resource_resp, downloaded]

        with self.assertRaisesRegex(RuntimeError, "không phải file PDF"):
            self.adapter.get_normalized_document(9, 1)

if __name__ == "__main__":
    unittest.main()
