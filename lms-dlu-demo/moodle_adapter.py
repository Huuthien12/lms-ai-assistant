import os
import requests
from dotenv import load_dotenv
from pathlib import Path
from urllib.parse import urlsplit

from deeptutor_integration.contracts import SourceDocument

load_dotenv()

class MoodleAdapter:
    def __init__(self, base_url: str = None, token: str = None):
        self.base_url = base_url or os.getenv("MOODLE_BASE_URL")
        self.token = token or os.getenv("MOODLE_TOKEN")

        if not self.base_url or not self.token:
            raise ValueError("MOODLE_BASE_URL và MOODLE_TOKEN phải được cấu hình.")

        self.rest_endpoint = f"{self.base_url.rstrip('/')}/webservice/rest/server.php"

    def _download_file(self, fileurl: str, resource_id: int):
        """Download a Moodle resource without exposing credential-bearing URLs."""
        try:
            source = urlsplit(self.base_url)
            target = urlsplit(fileurl)
            source_port = source.port or (443 if source.scheme == "https" else 80)
            target_port = target.port or (443 if target.scheme == "https" else 80)
        except (TypeError, ValueError):
            raise RuntimeError("Đường dẫn tải file Moodle không hợp lệ.") from None

        if (
            source.scheme not in {"http", "https"}
            or target.scheme not in {"http", "https"}
            or not source.hostname
            or not target.hostname
            or target.username
            or target.password
            or target.query
            or target.fragment
            or (source.scheme.lower(), source.hostname.lower(), source_port)
            != (target.scheme.lower(), target.hostname.lower(), target_port)
        ):
            raise RuntimeError("Đường dẫn tải file Moodle không hợp lệ.")

        try:
            response = requests.get(
                fileurl,
                params={"token": self.token},
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise RuntimeError(
                f"Lỗi HTTP khi tải file từ Moodle (resource_id={resource_id})."
            ) from None

        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int) and 300 <= status_code < 400:
            raise RuntimeError(
                f"Lỗi HTTP khi tải file từ Moodle (resource_id={resource_id}, status={status_code})."
            )
        try:
            response.raise_for_status()
        except requests.RequestException:
            raise RuntimeError(
                f"Lỗi HTTP khi tải file từ Moodle (resource_id={resource_id})."
            ) from None
        return response

    def _call_ws(self, function_name, **kwargs):
        """Hàm dùng chung để gọi Moodle Web Service với timeout và bắt lỗi HTTP/JSON."""
        params = {
            "wstoken": self.token,
            "wsfunction": function_name,
            "moodlewsrestformat": "json"
        }
        params.update(kwargs)

        request_failed = False
        try:
            response = requests.get(self.rest_endpoint, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException:
            request_failed = True
        if request_failed:
            raise RuntimeError("Lỗi HTTP khi gọi Moodle Web Service.")

        response_invalid = False
        try:
            data = response.json()
        except ValueError:
            response_invalid = True
        if response_invalid:
            raise RuntimeError("Định dạng dữ liệu trả về từ Moodle không hợp lệ (không phải JSON).")

        if isinstance(data, dict) and ("exception" in data or "errorcode" in data):
            raise RuntimeError("Moodle Web Service error.")

        return data

    def _enrolled_courses(self):
        response = self._call_ws(
            "core_course_get_enrolled_courses_by_timeline_classification",
            classification="all",
        )
        courses = response.get("courses") if isinstance(response, dict) else None
        if not isinstance(courses, list):
            raise RuntimeError("Moodle course data is invalid.")
        return [
            {"id": int(course["id"]), "shortname": str(course.get("shortname") or ""),
             "fullname": str(course.get("fullname") or "")}
            for course in courses
            if isinstance(course, dict) and str(course.get("id", "")).isdigit()
        ]

    def list_courses(self):
        return self._enrolled_courses()

    def get_course(self, course_id_moodle):
        course = next((item for item in self._enrolled_courses() if item["id"] == course_id_moodle), None)
        if not course:
            raise RuntimeError("Moodle course was not found.")
        return course

    def list_file_resources(self, course_id_moodle):
        resources_resp = self._call_ws("mod_resource_get_resources_by_courses", **{"courseids[0]": course_id_moodle})
        resources = resources_resp.get("resources", []) if isinstance(resources_resp, dict) else []
        output = []
        for resource in resources:
            files = resource.get("contentfiles", []) if isinstance(resource, dict) else []
            file_info = next((item for item in files if isinstance(item, dict) and item.get("filename") and item.get("fileurl")), None)
            if not file_info or not str(resource.get("id", "")).isdigit():
                continue
            extension = Path(str(file_info["filename"])).suffix.lower()
            output.append({"resource_id": int(resource["id"]), "filename": str(file_info["filename"]),
                           "mime_type": str(file_info.get("mimetype") or "application/octet-stream"),
                           "format": extension[1:].upper() if extension in {".pdf", ".docx", ".pptx", ".md"} else "UNSUPPORTED"})
        return output

    def get_source_document(self, course_id_moodle, resource_id) -> SourceDocument:
        """
        Lấy thông tin file, download và chuẩn hóa metadata.
        course_id_moodle: ID của khóa học trên hệ thống
        resource_id: ID của tài nguyên file
        """
        # 1. Lấy thông tin khóa học
        courses = self._enrolled_courses()
        if not courses or not isinstance(courses, list):
            raise RuntimeError("Không tìm thấy khóa học hoặc dữ liệu khóa học không hợp lệ")
        course_info = next(
            (course for course in courses if str(course.get("id")) == str(course_id_moodle)),
            None,
        )
        if not isinstance(course_info, dict):
            raise RuntimeError("Không tìm thấy khóa học hoặc dữ liệu khóa học không hợp lệ")

        # 2. Lấy danh sách tài nguyên của khóa học
        resources_resp = self._call_ws("mod_resource_get_resources_by_courses", **{"courseids[0]": course_id_moodle})
        resources = resources_resp.get("resources", []) if isinstance(resources_resp, dict) else []

        # 3. Tìm tài liệu tương ứng và kiểm tra an toàn contentfiles
        target_file = None
        for res in resources:
            if str(res.get("id")) == str(resource_id):
                contentfiles = res.get("contentfiles", [])
                if isinstance(contentfiles, list):
                    target_file = next(
                        (
                            item for item in contentfiles
                            if isinstance(item, dict)
                            and item.get("fileurl")
                        ),
                        None,
                    )
                break

        if not target_file:
            raise RuntimeError(f"Không tìm thấy tài liệu (resource_id={resource_id}) hoặc file đính kèm bị rỗng/thiếu")

        # 4. Lấy link và tải byte gốc của file
        fileurl = target_file.get("fileurl")
        if not fileurl:
            raise RuntimeError("Không tìm thấy đường dẫn tải file (fileurl) trong dữ liệu Moodle")

        file_response = self._download_file(fileurl, resource_id)

        content = file_response.content

        # Ngăn chặn trường hợp file rỗng hoặc bị chuyển hướng sang trang lỗi HTML.
        content_type = file_response.headers.get("Content-Type", "").lower()
        filename = target_file.get("filename", "document")
        if (
            not content
            or content_type.startswith("text/html")
            or content.lstrip().lower().startswith((b"<html", b"<!doctype html"))
        ):
            raise RuntimeError("Dữ liệu tải về không hợp lệ.")
        if filename.lower().endswith(".pdf") and not content.startswith(b"%PDF-"):
            raise RuntimeError("Dữ liệu PDF tải về không hợp lệ.")

        return SourceDocument(
            course_id=str(course_info.get("shortname", course_id_moodle)),
            document_id=str(resource_id),
            filename=filename,
            mime_type=target_file.get("mimetype") or content_type.split(";", 1)[0] or "application/octet-stream",
            source="moodle",
            metadata={
                "course_name": course_info.get("fullname", ""),
                "moodle_file_size": target_file.get("filesize", 0)
            },
            content=content,
        )

    def get_normalized_document(self, course_id_moodle, resource_id) -> SourceDocument:
        """Backward-compatible alias; callers now receive original source bytes."""
        return self.get_source_document(course_id_moodle, resource_id)
