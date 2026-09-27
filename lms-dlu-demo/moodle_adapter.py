import os
import requests
from dotenv import load_dotenv

load_dotenv()

class MoodleAdapter:
    def __init__(self):
        self.base_url = os.getenv("MOODLE_BASE_URL")
        self.token = os.getenv("MOODLE_TOKEN")
        self.rest_endpoint = f"{self.base_url}/webservice/rest/server.php"

    def _call_ws(self, function_name, **kwargs):
        """Hàm dùng chung để gọi Moodle Web Service"""
        params = {
            "wstoken": self.token,
            "wsfunction": function_name,
            "moodlewsrestformat": "json"
        }
        params.update(kwargs)
        response = requests.get(self.rest_endpoint, params=params)
        return response.json()

    def get_normalized_document(self, course_id_moodle, resource_id):
        """
        Lấy thông tin file, download và chuẩn hóa theo Contract.
        course_id_moodle: ID của khóa học trên hệ thống (của bạn là 9)
        resource_id: ID của tài nguyên file PDF
        """
        # 1. Lấy thông tin khóa học (để lấy shortname và fullname)
        courses = self._call_ws("core_course_get_courses", **{"options[ids][0]": course_id_moodle})
        if not courses:
            raise Exception("Không tìm thấy khóa học")
        course_info = courses[0]

        # 2. Lấy danh sách tài nguyên của khóa học
        resources = self._call_ws("mod_resource_get_resources_by_courses", **{"courseids[0]": course_id_moodle})
        
        # Tìm file có resource_id tương ứng
        target_file = None
        for res in resources.get("resources", []):
            if res["id"] == resource_id:
                target_file = res["contentfiles"][0] # Lấy file đầu tiên trong resource
                break
                
        if not target_file:
            raise Exception("Không tìm thấy tài liệu")

        # 3. Download file PDF (dạng bytes)
        fileurl = target_file["fileurl"]
        download_url = f"{fileurl}?token={self.token}"
        pdf_response = requests.get(download_url)
        pdf_bytes = pdf_response.content 

        # 4. Chuẩn hóa dữ liệu theo Contract chung
        normalized_doc = {
            "course_id": course_info["shortname"], 
            "document_id": str(resource_id),       
            "filename": target_file["filename"],   
            "mime_type": target_file["mimetype"],  
            "source": "moodle",
            "metadata": {
                "course_name": course_info["fullname"] 
            },
            "path": download_url 
        }

        return normalized_doc, pdf_bytes

# --- PHẦN CHẠY TEST ---
if __name__ == "__main__":
    adapter = MoodleAdapter()
    
    # Chạy thử hàm với ID khóa học = 9, ID tài nguyên = 1 (bạn thay số 1 bằng ID thực tế của Chuong 1.pdf nếu khác)
    doc_meta, pdf_data = adapter.get_normalized_document(course_id_moodle=9, resource_id=1)

    print("--- KẾT QUẢ CHUẨN HÓA (CONTRACT) ---")
    print(doc_meta)
    print(f"\nKích thước file tải về: {len(pdf_data)} bytes")

    # Lưu thử file ra máy để kiểm chứng
    with open(doc_meta["filename"], "wb") as f:
        f.write(pdf_data)
    print(f"Đã lưu thành công file {doc_meta['filename']} vào thư mục hiện tại để kiểm tra!")