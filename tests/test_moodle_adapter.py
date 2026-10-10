import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import traceback

# Cho phép import MoodleAdapter từ thư mục lms-dlu-demo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'lms-dlu-demo')))
from moodle_adapter import MoodleAdapter

class TestMoodleAdapter(unittest.TestCase):
    def setUp(self):
        self.fake_token = "secret_mock_token_123"
        self.adapter = MoodleAdapter(base_url="https://fake-moodle.edu.vn", token=self.fake_token)

    @staticmethod
    def enrolled_courses(*courses):
        return {"courses": list(courses)}

    @patch("moodle_adapter.requests.get")
    def test_course_discovery_uses_enrolled_courses_only(self, mock_get):
        response = MagicMock()
        response.json.return_value = self.enrolled_courses(
            {"id": 3, "shortname": "INT2001", "fullname": "AI"}
        )
        mock_get.return_value = response

        self.assertEqual(
            self.adapter.list_courses(),
            [{"id": 3, "shortname": "INT2001", "fullname": "AI"}],
        )
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["wsfunction"], "core_course_get_enrolled_courses_by_timeline_classification")
        self.assertEqual(params["classification"], "all")
        self.assertNotIn("options[ids][0]", params)

    @patch("moodle_adapter.requests.get")
    def test_rest_success_response_preserves_contract(self, mock_get):
        response = MagicMock()
        response.json.return_value = {"courses": []}
        mock_get.return_value = response

        self.assertEqual(self.adapter._call_ws("core_course_get_enrolled_courses_by_timeline_classification"), {"courses": []})
        self.assertEqual(mock_get.call_args.kwargs["timeout"], 15)
        self.assertEqual(mock_get.call_args.kwargs["params"]["wstoken"], self.fake_token)

    @patch("moodle_adapter.requests.get")
    def test_rest_transport_failure_is_redacted_from_exception_context_and_traceback(self, mock_get):
        import requests
        unsafe_url = f"https://fake-moodle.edu.vn/rest?wstoken={self.fake_token}"
        mock_get.side_effect = requests.exceptions.Timeout(unsafe_url)

        with self.assertRaisesRegex(RuntimeError, "Lỗi HTTP khi gọi Moodle Web Service") as raised:
            self.adapter._call_ws("core_course_get_enrolled_courses_by_timeline_classification")

        formatted = "".join(traceback.format_exception(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(self.fake_token, formatted)
        self.assertNotIn("wstoken=", formatted)
        self.assertNotIn(unsafe_url, formatted)

    @patch("moodle_adapter.requests.get")
    def test_rest_http_failure_is_redacted_from_traceback(self, mock_get):
        import requests
        unsafe_url = f"https://fake-moodle.edu.vn/rest?wstoken={self.fake_token}"
        response = MagicMock()
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(unsafe_url)
        mock_get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "Lỗi HTTP khi gọi Moodle Web Service") as raised:
            self.adapter._call_ws("core_course_get_enrolled_courses_by_timeline_classification")

        formatted = "".join(traceback.format_exception(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(self.fake_token, formatted)
        self.assertNotIn("wstoken=", formatted)
        self.assertNotIn(unsafe_url, formatted)

    @patch("moodle_adapter.requests.get")
    def test_malformed_rest_response_is_redacted_from_traceback(self, mock_get):
        unsafe_url = f"https://fake-moodle.edu.vn/rest?wstoken={self.fake_token}"
        response = MagicMock()
        response.json.side_effect = ValueError(unsafe_url)
        mock_get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "không phải JSON") as raised:
            self.adapter._call_ws("core_course_get_enrolled_courses_by_timeline_classification")

        formatted = "".join(traceback.format_exception(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(self.fake_token, formatted)
        self.assertNotIn("wstoken=", formatted)
        self.assertNotIn(unsafe_url, formatted)

    @patch("moodle_adapter.requests.get")
    def test_selected_course_must_be_enrolled(self, mock_get):
        response = MagicMock()
        response.json.return_value = self.enrolled_courses(
            {"id": 3, "shortname": "INT2001", "fullname": "AI"}
        )
        mock_get.return_value = response

        with self.assertRaisesRegex(RuntimeError, "Moodle course was not found"):
            self.adapter.get_course(99)
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["wsfunction"],
            "core_course_get_enrolled_courses_by_timeline_classification",
        )

    @patch("moodle_adapter.requests.get")
    def test_source_document_cannot_bypass_enrolled_course_scope(self, mock_get):
        response = MagicMock()
        response.json.return_value = self.enrolled_courses()
        mock_get.return_value = response

        with self.assertRaises(RuntimeError):
            self.adapter.get_source_document(99, 1)
        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(
            mock_get.call_args.kwargs["params"]["wsfunction"],
            "core_course_get_enrolled_courses_by_timeline_classification",
        )

    @patch("moodle_adapter.requests.get")
    def test_success_normalization(self, mock_get):
        # Thiết lập mock responses
        course_resp = MagicMock()
        course_resp.json.return_value = [{"id": 9, "shortname": "INT1339", "fullname": "Kiến trúc máy tính"}]

        course_resp.json.return_value = self.enrolled_courses(*course_resp.json.return_value)
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

        source = self.adapter.get_source_document(course_id_moodle=9, resource_id=1)

        # 1 & 2. Kiểm tra normalization thành công và fields chuẩn
        self.assertEqual(source.course_id, "INT1339")
        self.assertEqual(source.document_id, "1")
        self.assertEqual(source.filename, "Chuong1.pdf")
        self.assertEqual(source.mime_type, "application/pdf")
        self.assertEqual(source.source, "moodle")

        # 3. PDF bytes được trả riêng
        self.assertEqual(source.content, b"%PDF-1.4 FAKE PDF CONTENT")
        self.assertEqual(mock_get.call_args_list[2].kwargs["params"], {"token": self.fake_token})
        self.assertEqual(mock_get.call_args_list[2].kwargs["timeout"], 30)
        self.assertFalse(mock_get.call_args_list[2].kwargs["allow_redirects"])

        # 4 & 5. Không lộ token và không lưu URL/path
        doc_str = str(source.model_dump())
        self.assertNotIn(self.fake_token, doc_str)
        self.assertNotIn("token=", doc_str)
        self.assertNotIn("https://fake-moodle", doc_str)

    @patch("moodle_adapter.requests.get")
    def test_missing_resource(self, mock_get):
        # 6. Resource không tồn tại
        course_resp = MagicMock()
        course_resp.json.return_value = self.enrolled_courses({"id": 9})

        resource_resp = MagicMock()
        resource_resp.json.return_value = {"resources": []}

        mock_get.side_effect = [course_resp, resource_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_source_document(9, 999)
        self.assertIn("Không tìm thấy tài liệu", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_empty_contentfiles(self, mock_get):
        # 7. Contentfiles thiếu/rỗng
        course_resp = MagicMock()
        course_resp.json.return_value = self.enrolled_courses({"id": 9})

        resource_resp = MagicMock()
        resource_resp.json.return_value = {
            "resources": [{"id": 1, "contentfiles": []}]
        }

        mock_get.side_effect = [course_resp, resource_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_source_document(9, 1)
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
            self.adapter.get_source_document(9, 1)
        self.assertIn("Moodle Web Service error", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_pdf_download_http_failure(self, mock_get):
        # 9. PDF download HTTP failure
        import requests
        course_resp = MagicMock()
        course_resp.json.return_value = self.enrolled_courses({"id": 9})

        resource_resp = MagicMock()
        resource_resp.json.return_value = {
            "resources": [{"id": 1, "contentfiles": [{"fileurl": "https://fake-moodle.edu.vn/file"}]}]
        }

        pdf_resp = MagicMock()
        pdf_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"https://fake-moodle.edu.vn/file?token={self.fake_token}"
        )

        mock_get.side_effect = [course_resp, resource_resp, pdf_resp]

        with self.assertRaises(RuntimeError) as context:
            self.adapter.get_normalized_document(9, 1)
        self.assertIn("Lỗi HTTP khi tải file", str(context.exception))
        self.assertIsNone(context.exception.__cause__)
        self.assertNotIn(self.fake_token, str(context.exception))
        self.assertNotIn("token=", str(context.exception))
        self.assertNotIn("file?", str(context.exception))

    @patch("moodle_adapter.requests.get")
    def test_rejects_non_pdf_download(self, mock_get):
        course_resp = MagicMock()
        course_resp.json.return_value = self.enrolled_courses({"id": 9, "shortname": "INT1339"})
        resource_resp = MagicMock()
        resource_resp.json.return_value = {"resources": [{"id": 1, "contentfiles": [{
            "filename": "chapter.pdf", "mimetype": "application/pdf", "fileurl": "https://fake-moodle.edu.vn/file"
        }]}]}
        downloaded = MagicMock()
        downloaded.content = b"<html>login</html>"
        downloaded.headers = {"Content-Type": "text/html"}
        mock_get.side_effect = [course_resp, resource_resp, downloaded]

        with self.assertRaisesRegex(RuntimeError, "không hợp lệ"):
            self.adapter.get_source_document(9, 1)

    @patch("moodle_adapter.requests.get")
    def test_preserves_non_pdf_original_bytes(self, mock_get):
        for filename, mime_type, content in (
            ("chapter.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"docx"),
            ("chapter.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", b"pptx"),
            ("chapter.md", "text/markdown", b"# markdown"),
        ):
            course = MagicMock(); course.json.return_value = self.enrolled_courses({"id": 9, "shortname": "INT1339"})
            resources = MagicMock(); resources.json.return_value = {"resources": [{"id": 1, "contentfiles": [{
                "filename": filename, "mimetype": mime_type, "fileurl": "https://fake-moodle.edu.vn/file"
            }]}]}
            downloaded = MagicMock(); downloaded.content = content; downloaded.headers = {"Content-Type": mime_type}
            mock_get.side_effect = [course, resources, downloaded]
            retrieved = self.adapter.get_source_document(9, 1)
            self.assertEqual((retrieved.filename, retrieved.mime_type, retrieved.content), (filename, mime_type, content))
            mock_get.reset_mock()

    def _source_responses(self, fileurl):
        course = MagicMock()
        course.json.return_value = self.enrolled_courses({"id": 9, "shortname": "INT1339"})
        resources = MagicMock()
        resources.json.return_value = {"resources": [{"id": 1, "contentfiles": [{
            "filename": "chapter.pdf", "mimetype": "application/pdf", "fileurl": fileurl,
        }]}]}
        return course, resources

    @patch("moodle_adapter.requests.get")
    def test_rejects_untrusted_file_urls_before_network_request(self, mock_get):
        invalid_urls = (
            "https://other.example/file.pdf",
            "https://user:password@fake-moodle.edu.vn/file.pdf",
            "ftp://fake-moodle.edu.vn/file.pdf",
            "https://fake-moodle.edu.vn:invalid/file.pdf",
            "not a URL",
        )
        for fileurl in invalid_urls:
            with self.subTest(fileurl=fileurl):
                course, resources = self._source_responses(fileurl)
                mock_get.side_effect = [course, resources]
                with self.assertRaisesRegex(RuntimeError, "không hợp lệ") as raised:
                    self.adapter.get_source_document(9, 1)
                self.assertNotIn(self.fake_token, str(raised.exception))
                self.assertNotIn(fileurl, str(raised.exception))
                self.assertEqual(mock_get.call_count, 2)
                mock_get.reset_mock()

    @patch("moodle_adapter.requests.get")
    def test_rejects_redirects_without_following_or_leaking_location(self, mock_get):
        for location in ("https://fake-moodle.edu.vn/next", "https://other.example/next"):
            with self.subTest(location=location):
                course, resources = self._source_responses("https://fake-moodle.edu.vn/file.pdf")
                redirect = MagicMock(status_code=302, headers={"Location": location})
                mock_get.side_effect = [course, resources, redirect]
                with self.assertRaisesRegex(RuntimeError, "status=302") as raised:
                    self.adapter.get_source_document(9, 1)
                self.assertNotIn(location, str(raised.exception))
                self.assertNotIn(self.fake_token, str(raised.exception))
                self.assertEqual(mock_get.call_count, 3)
                self.assertFalse(mock_get.call_args.kwargs["allow_redirects"])
                mock_get.reset_mock()

    @patch("moodle_adapter.requests.get")
    def test_download_transport_failures_are_redacted_and_unchained(self, mock_get):
        import requests
        unsafe_error = requests.exceptions.Timeout(
            f"https://fake-moodle.edu.vn/file.pdf?token={self.fake_token}"
        )
        course, resources = self._source_responses("https://fake-moodle.edu.vn/file.pdf")
        mock_get.side_effect = [course, resources, unsafe_error]

        with self.assertRaisesRegex(RuntimeError, "resource_id=1") as raised:
            self.adapter.get_source_document(9, 1)

        self.assertIsNone(raised.exception.__cause__)
        self.assertNotIn(self.fake_token, str(raised.exception))
        self.assertNotIn("token=", str(raised.exception))
        self.assertNotIn("file.pdf", str(raised.exception))

    @patch("moodle_adapter.requests.get")
    def test_rejects_empty_html_and_invalid_pdf_payloads(self, mock_get):
        cases = (
            (b"", "application/pdf"),
            (b"<html>login</html>", "text/html"),
            (b"not a PDF", "application/pdf"),
        )
        for content, content_type in cases:
            with self.subTest(content=content):
                course, resources = self._source_responses("https://fake-moodle.edu.vn/file.pdf")
                response = MagicMock(status_code=200, content=content, headers={"Content-Type": content_type})
                mock_get.side_effect = [course, resources, response]
                with self.assertRaisesRegex(RuntimeError, "không hợp lệ") as raised:
                    self.adapter.get_source_document(9, 1)
                self.assertNotIn(self.fake_token, str(raised.exception))
                self.assertNotIn("file.pdf", str(raised.exception))
                mock_get.reset_mock()


if __name__ == "__main__":
    unittest.main()
