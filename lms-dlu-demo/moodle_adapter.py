import os
import requests
from dotenv import load_dotenv

load_dotenv()

class MoodleAdapter:
    def __init__(self, base_url: str = None, token: str = None):
        self.base_url = base_url or os.getenv("MOODLE_BASE_URL")
        self.token = token or os.getenv("MOODLE_TOKEN")

        if not self.base_url or not self.token:
            raise ValueError("MOODLE_BASE_URL và MOODLE_TOKEN phải được cấu hình.")

        self.rest_endpoint = f"{self.base_url.rstrip('/')}/webservice/rest/server.php"

    def _call_ws(self, function_name, **kwargs):
        """Hàm dùng chung để gọi Moodle Web Service với timeout và bắt lỗi HTTP/JSON."""
        params = {
            "wstoken": self.token,
            "wsfunction": function_name,
            "moodlewsrestformat": "json"
        }
        params.update(kwargs)

        try:
            response = requests.get(self.rest_endpoint, params=params, timeout=15)
            response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError("Lỗi HTTP khi gọi Moodle Web Service.") from e

        try:
            data = response.json()
        except ValueError:
            raise RuntimeError("Định dạng dữ liệu trả về từ Moodle không hợp lệ (không phải JSON).")

        if isinstance(data, dict) and ("exception" in data or "errorcode" in data):
            raise RuntimeError("Moodle Web Service error.")

        return data

    def get_normalized_document(self, course_id_moodle, resource_id):
        """
        Lấy thông tin file, download và chuẩn hóa metadata.
        course_id_moodle: ID của khóa học trên hệ thống
        resource_id: ID của tài nguyên file
        """
        # 1. Lấy thông tin khóa học
        courses = self._call_ws("core_course_get_courses", **{"options[ids][0]": course_id_moodle})
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

        # 4. Lấy link và tải byte của file PDF
        fileurl = target_file.get("fileurl")
        if not fileurl:
            raise RuntimeError("Không tìm thấy đường dẫn tải file (fileurl) trong dữ liệu Moodle")

        try:
            pdf_response = requests.get(fileurl, params={"token": self.token}, timeout=30)
            pdf_response.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError("Lỗi HTTP khi tải file PDF từ Moodle.") from e

        pdf_bytes = pdf_response.content

        # Ngăn chặn trường hợp file rỗng hoặc bị chuyển hướng sang trang lỗi HTML
        content_type = pdf_response.headers.get("Content-Type", "").lower()
        if (
            not pdf_bytes
            or not pdf_bytes.startswith(b"%PDF-")
            or content_type.startswith("text/html")
        ):
            raise RuntimeError("Dữ liệu tải về không hợp lệ (không phải file PDF, có thể do lỗi xác thực).")

        # 5. Chuẩn hóa metadata (Loại bỏ token và các URL tải mạng, KHÔNG gán path)
        normalized_doc = {
            "course_id": str(course_info.get("shortname", course_id_moodle)),
            "document_id": str(resource_id),
            "filename": target_file.get("filename", "document.pdf"),
            "mime_type": target_file.get("mimetype", "application/pdf"),
            "source": "moodle",
            "metadata": {
                "course_name": course_info.get("fullname", ""),
                "moodle_file_size": target_file.get("filesize", 0)
            }
        }

        return normalized_doc, pdf_bytes
