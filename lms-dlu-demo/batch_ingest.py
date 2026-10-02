from deeptutor_client import DeepTutorAPIClient, create_deeptutor_client

def get_client() -> DeepTutorAPIClient:
    return create_deeptutor_client()

def run_batch_ingestion():
    client = get_client()
    kb_name = "int1339-python"

    # Giả lập danh sách tài liệu của môn Kiến trúc máy tính (course_id: 9)
    # Ví dụ: Chuong 1, Chuong 2, Chuong 3
    resources_to_sync = [
        {"course_id": 9, "resource_id": 1, "name": "Chuong 1.pdf"},
        {"course_id": 9, "resource_id": 2, "name": "Chuong 2.pdf"},
        {"course_id": 9, "resource_id": 3, "name": "Chuong 3.pdf"},
    ]

    print(f"Bắt đầu đồng bộ {len(resources_to_sync)} tài liệu vào KB: '{kb_name}'...\n")

    for item in resources_to_sync:
        print(f"Đang xử lý: {item['name']} (Resource ID: {item['resource_id']})")
        try:
            result = client.ingest_resource(
                course_id_moodle=item["course_id"],
                resource_id=item["resource_id"],
                kb_name=kb_name
            )
            print(f"Kết quả: {result['status']} - {result.get('message', '')}\n")
        except Exception as e:
            print(f"Lỗi khi đồng bộ {item['name']}: {e}\n")

    print("Hoàn tất quá trình đồng bộ!")

if __name__ == "__main__":
    run_batch_ingestion()
