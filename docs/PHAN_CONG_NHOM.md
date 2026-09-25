# PHÂN CÔNG CÔNG VIỆC NHÓM -- ĐỒ ÁN DEEPTUTOR TÍCH HỢP LMS

## 1. Thông tin chung

**Đề tài:** Tìm hiểu DeepTutor và xây dựng ứng dụng minh họa tích hợp dữ
liệu từ LMS.

**Mục tiêu chung:** Xây dựng hệ thống trợ lý học tập có khả năng tiếp
nhận dữ liệu/tài liệu từ LMS, đưa tài liệu vào DeepTutor để xây dựng
Knowledge Base (KB), hỗ trợ truy vấn theo RAG và kết hợp mô-đun AI nhằm
hướng tới hỗ trợ học tập cá nhân hóa.

### Thành viên và phạm vi chính

  -----------------------------------------------------------------------
  Thành viên              Phụ trách               Trách nhiệm chính
  ----------------------- ----------------------- -----------------------
  **Lương Hữu Thiện**     **DeepTutor**           DeepTutor, KB/RAG,
                                                  ingest tài liệu, truy
                                                  vấn, API tích hợp
                                                  DeepTutor

  **Nguyễn Hồng Phúc      **LMS / Moodle**        Moodle/LMS, dữ liệu
  Thọ**                                           khóa học, người dùng,
                                                  tài liệu, API/adapter
                                                  LMS

  **Hoàng Bình Quân**     **AI**                  AI Assistant, xử lý ngữ
                                                  cảnh, prompt, cá nhân
                                                  hóa và logic AI
  -----------------------------------------------------------------------

> **Nguyên tắc:** Mỗi thành viên chịu trách nhiệm chính cho mô-đun của
> mình. Các mô-đun giao tiếp qua interface/API rõ ràng để có thể phát
> triển và kiểm thử tương đối độc lập.

------------------------------------------------------------------------

## 2. Kiến trúc phân chia công việc

``` text
                    ┌──────────────────────┐
                    │     LMS / Moodle     │
                    │ Nguyễn Hồng Phúc Thọ │
                    └──────────┬───────────┘
                               │
                        Dữ liệu chuẩn hóa
                               │
                               ▼
                    ┌──────────────────────┐
                    │ Integration Contract │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ DeepTutor Integration│
                    │ Lương Hữu Thiện      │
                    └──────────┬───────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │ DeepTutor / KB / RAG │
                    └──────────────────────┘

              ┌──────────────────────────────┐
              │ AI Assistant / Personalization│
              │ Hoàng Bình Quân             │
              └──────────────────────────────┘
```

**Mục tiêu thiết kế quan trọng:** Khi LMS demo được thay bằng Moodle
thật, phần DeepTutor không phải viết lại. Thọ chỉ cần chuyển dữ liệu
Moodle về contract chung mà mô-đun DeepTutor chấp nhận.

------------------------------------------------------------------------

# 3. LƯƠNG HỮU THIỆN -- DEEPTUTOR

## 3.1. Mục tiêu

Xây dựng lớp tích hợp DeepTutor độc lập với LMS, chịu trách nhiệm biến
tài liệu học tập thành nguồn tri thức có thể truy vấn và cung cấp
interface ổn định cho LMS/AI sử dụng.

## 3.2. Công việc cần thực hiện

### A. Nền tảng DeepTutor

-   Quản lý source DeepTutor upstream bằng Git submodule.
-   Kiểm tra phiên bản DeepTutor sử dụng trong đồ án.
-   Thiết lập môi trường Python và dependency cần thiết.
-   Chuẩn hóa cấu hình và đường dẫn, tránh hard-code đường dẫn máy cá
    nhân.
-   Kiểm tra khả năng khởi động và trạng thái DeepTutor.

### B. Knowledge Base và RAG

-   Tạo Knowledge Base.
-   Liệt kê và kiểm tra trạng thái KB.
-   Nạp tài liệu học tập vào KB.
-   Theo dõi trạng thái xử lý tài liệu.
-   Tìm kiếm/truy vấn nội dung trong KB.
-   Kiểm thử RAG bằng tài liệu môn học thực tế.
-   Xử lý trường hợp KB chưa tồn tại, chưa ready hoặc tài liệu lỗi.

### C. Document ingestion

Thiết kế đầu vào trung lập, tối thiểu hỗ trợ: - `document_id` -
`course_id` - `filename` - `content` hoặc `path` - `mime_type` -
`source` - `metadata`

DeepTutor **không được phụ thuộc trực tiếp vào schema Moodle hoặc SQL
Server của LMS**.

### D. API / Integration Contract

Xây dựng hoặc chuẩn hóa các chức năng tương đương:

``` text
POST /deeptutor/documents
POST /deeptutor/knowledge-bases
POST /deeptutor/query
GET  /deeptutor/health
GET  /deeptutor/status
```

Tên endpoint có thể điều chỉnh theo code thực tế nhưng phải giữ contract
rõ ràng.

### E. Xử lý lỗi

-   DeepTutor runtime không hoạt động.
-   KB không tồn tại.
-   KB chưa sẵn sàng.
-   File không hợp lệ.
-   Truy vấn thiếu dữ liệu.
-   Lỗi CLI/process.
-   Lỗi external LLM/API.
-   Timeout.

Trả lỗi có cấu trúc để LMS và AI có thể xử lý.

### F. Kiểm thử

-   Import/compile module.
-   Configuration/path resolution.
-   Health check.
-   Tạo/đọc trạng thái KB.
-   Validation tài liệu.
-   Validation câu hỏi.
-   Query KB.
-   Trường hợp DeepTutor unavailable.
-   Contract với LMS caller.
-   End-to-end khi có đủ API key/runtime.

## 3.3. Không thuộc phần Thiện

-   Không xây Moodle.
-   Không xây database/schema LMS thay Thọ.
-   Không triển khai chức năng quản lý sinh viên/giảng viên.
-   Không làm logic cá nhân hóa AI thay Quân.
-   Không sửa source upstream DeepTutor nếu không thật sự cần.

## 3.4. Kết quả bàn giao

-   DeepTutor chạy được trong môi trường đồ án.
-   Có KB mẫu và tài liệu kiểm thử.
-   Có API/interface để nhận tài liệu và truy vấn.
-   Có tài liệu contract để LMS/AI tích hợp.
-   Có test cho các chức năng chính.
-   Có hướng dẫn cấu hình/chạy mô-đun.

------------------------------------------------------------------------

# 4. NGUYỄN HỒNG PHÚC THỌ -- LMS / MOODLE

## 4.1. Mục tiêu

Phụ trách nguồn dữ liệu học tập và LMS. Xây dựng lớp kết nối để dữ liệu
từ LMS/Moodle có thể chuyển sang DeepTutor thông qua contract chung.

## 4.2. Công việc cần thực hiện

### A. Nghiên cứu Moodle/LMS

-   Tìm hiểu cấu trúc Moodle.
-   Xác định các đối tượng cần dùng:
    -   User/Sinh viên/Giảng viên.
    -   Course.
    -   Enrollment.
    -   Resource/File.
    -   Assignment nếu cần.
    -   Progress/completion nếu phạm vi đồ án sử dụng.
-   Xác định phương thức lấy dữ liệu phù hợp: Moodle Web Services/API
    hoặc lớp adapter được nhóm thống nhất.

### B. LMS hiện tại

-   Duy trì phần LMS demo cần thiết cho quá trình phát triển.
-   Quản lý dữ liệu khóa học.
-   Quản lý tài liệu học tập.
-   Phân biệt dữ liệu sinh viên/giảng viên khi chức năng yêu cầu.
-   Chuẩn hóa API/data model của LMS.

### C. Moodle Adapter

Chuyển dữ liệu Moodle thành contract chung, ví dụ:

``` text
Moodle file
     ↓
Moodle Adapter
     ↓
{
    document_id,
    course_id,
    filename,
    mime_type,
    source,
    metadata
}
     ↓
DeepTutor API
```

### D. Tích hợp tài liệu

-   Lấy tài liệu theo course.
-   Gửi tài liệu sang DeepTutor.
-   Theo dõi kết quả ingest.
-   Lưu mapping nếu cần giữa Moodle resource và DeepTutor document/KB.
-   Tránh ingest trùng tài liệu khi có thể xác định.

### E. Kiểm thử

-   Đọc danh sách course.
-   Đọc tài liệu của course.
-   Mapping dữ liệu.
-   Gửi tài liệu sang contract DeepTutor.
-   Xử lý tài liệu lỗi/thiếu.
-   Kiểm tra thay LMS demo bằng Moodle mà không phải sửa logic
    DeepTutor.

## 4.3. Không thuộc phần Thọ

-   Không sửa thuật toán RAG của DeepTutor.
-   Không triển khai KB internals.
-   Không xây logic prompt/cá nhân hóa AI thay Quân.

## 4.4. Kết quả bàn giao

-   LMS/Moodle cung cấp được dữ liệu cần thiết.
-   Có adapter chuyển dữ liệu sang contract chung.
-   Có luồng gửi tài liệu LMS → DeepTutor.
-   Có tài liệu mô tả dữ liệu/API.
-   Có test cho mapping và tích hợp.

------------------------------------------------------------------------

# 5. HOÀNG BÌNH QUÂN -- AI

## 5.1. Mục tiêu

Phụ trách tầng AI Assistant và logic sử dụng ngữ cảnh học tập, đồng thời
giữ AI tách khỏi chi tiết triển khai của Moodle và DeepTutor.

## 5.2. Công việc cần thực hiện

### A. AI Assistant

-   Xác định luồng hỏi đáp của trợ lý.
-   Thiết kế prompt/system instruction phù hợp với trợ lý học tập.
-   Nhận câu hỏi người dùng.
-   Nhận context/nguồn tri thức được cung cấp qua integration.
-   Chuẩn hóa kết quả trả về cho giao diện.

### B. Context

Xác định context cần thiết, ví dụ: - `user_id` - `course_id` - câu hỏi -
tài liệu/ngữ cảnh truy xuất - lịch sử hội thoại ở mức cần thiết

Không phụ thuộc trực tiếp vào bảng database Moodle.

### C. Cá nhân hóa

Trong phạm vi đồ án có thể triển khai: - Gắn câu hỏi với môn học đang
chọn. - Điều chỉnh câu trả lời dựa trên context học tập được cung cấp. -
Gợi ý nội dung cần ôn dựa trên dữ liệu đầu vào hợp lệ. - Giữ logic cá
nhân hóa tách khỏi DeepTutor KB internals.

### D. Prompt và response

-   Thiết kế prompt template.
-   Kiểm soát trường hợp thiếu context.
-   Quy định response format.
-   Xử lý trường hợp không tìm thấy kiến thức phù hợp.
-   Hạn chế câu trả lời không dựa trên tài liệu khi chức năng yêu cầu
    grounded answer.

### E. Kiểm thử

-   Câu hỏi có context.
-   Câu hỏi không có context.
-   Context sai course.
-   Không tìm thấy tài liệu liên quan.
-   Prompt/response format.
-   Luồng AI nhận dữ liệu từ các interface của hệ thống.

## 5.3. Không thuộc phần Quân

-   Không xây Moodle/database thay Thọ.
-   Không quản lý DeepTutor KB/RAG internals thay Thiện.
-   Không sửa DeepTutor upstream.

## 5.4. Kết quả bàn giao

-   Luồng AI Assistant hoạt động.
-   Prompt/template rõ ràng.
-   Có interface đầu vào/đầu ra.
-   Có xử lý context/cá nhân hóa trong phạm vi đã thống nhất.
-   Có test các tình huống AI chính.

------------------------------------------------------------------------

# 6. CONTRACT CHUNG GIỮA 3 THÀNH VIÊN

Đây là phần cả nhóm cần thống nhất sớm để tránh code xong mới không ghép
được.

## 6.1. Document Contract

Ví dụ:

``` json
{
  "document_id": "doc_001",
  "course_id": "INT1339",
  "filename": "lecture01.pdf",
  "mime_type": "application/pdf",
  "source": "moodle",
  "metadata": {
    "title": "Bài giảng 1"
  }
}
```

## 6.2. Query Contract

Ví dụ:

``` json
{
  "user_id": "student_001",
  "course_id": "INT1339",
  "question": "Phương thức append trong List dùng để làm gì?",
  "kb_id": "lms-int1339"
}
```

## 6.3. Response Contract

Ví dụ:

``` json
{
  "success": true,
  "answer": "...",
  "kb_id": "lms-int1339",
  "sources": [],
  "error": null
}
```

Các trường có thể thay đổi khi triển khai, nhưng mọi thay đổi contract
phải được cả ba thành viên biết.

------------------------------------------------------------------------

# 7. TRÌNH TỰ LÀM VIỆC ĐỀ XUẤT

  ----------------------------------------------------------------------------
  Giai đoạn         Thiện --          Thọ -- LMS/Moodle Quân -- AI
                    DeepTutor
  ----------------- ----------------- ----------------- ----------------------
  **1. Chuẩn hóa**  DeepTutor         Xác định dữ liệu  Xác định
                    runtime, KB, API  LMS/Moodle        input/context/output
                    contract                            AI

  **2. Phát triển   Ingest + query +  Course/document   Prompt + AI flow
  độc lập**         health            adapter

  **3. Contract     Mock LMS request  Mock DeepTutor    Mock context/retrieval
  test**                              endpoint

  **4. Tích hợp**   Nhận tài liệu và  Gửi dữ liệu thật  Nhận context và tạo
                    query                               response

  **5. Moodle**     Giữ DeepTutor     Thay adapter bằng Giữ AI interface
                    interface         Moodle thật

  **6. E2E**        KB/RAG            Moodle/LMS        AI Assistant
  ----------------------------------------------------------------------------

------------------------------------------------------------------------

# 8. TIÊU CHÍ HOÀN THÀNH TÍCH HỢP

Luồng cuối cần chứng minh được:

``` text
1. Người dùng / LMS chọn môn học
            ↓
2. LMS lấy tài liệu của môn
            ↓
3. LMS Adapter chuẩn hóa dữ liệu
            ↓
4. DeepTutor nhận và ingest tài liệu
            ↓
5. Knowledge Base sẵn sàng
            ↓
6. Người dùng đặt câu hỏi
            ↓
7. Hệ thống truy xuất kiến thức phù hợp
            ↓
8. AI xử lý context/response theo thiết kế
            ↓
9. Kết quả được trả về giao diện
```

Nhóm cần kiểm thử ít nhất một luồng end-to-end bằng tài liệu học tập
thực tế.

------------------------------------------------------------------------

# 9. QUY TẮC GIT VÀ PHỐI HỢP

-   Không sửa trực tiếp phần của thành viên khác nếu chưa thống nhất.
-   Mỗi người phát triển trên branch riêng khi bắt đầu triển khai song
    song.
-   Commit nhỏ, có nội dung rõ ràng.
-   Không commit `.env`, API key, password, database runtime, `venv`,
    cache hoặc file tạm.
-   Không tự ý thay đổi integration contract mà không thông báo hai
    thành viên còn lại.
-   Trước khi merge cần chạy test của module mình.
-   Nếu thay đổi API/contract, cập nhật tài liệu cùng commit.
-   `DeepTutor/` là upstream submodule; không sửa trực tiếp nếu không có
    lý do kỹ thuật được nhóm thống nhất.

------------------------------------------------------------------------

# 10. TÓM TẮT ĐỂ CẢ NHÓM NHỚ

**Thiện -- DeepTutor:** "Tài liệu đã được đưa cho tôi → tôi biến nó
thành KB/RAG có thể truy vấn và cung cấp interface ổn định."

**Thọ -- LMS/Moodle:** "Tôi lấy đúng dữ liệu/tài liệu từ LMS/Moodle →
chuẩn hóa → gửi cho DeepTutor."

**Quân -- AI:** "Tôi nhận câu hỏi + context → điều khiển logic AI/cá
nhân hóa → tạo phản hồi phù hợp."

Nếu giữ đúng ba ranh giới trên, LMS demo có thể được thay bằng Moodle
thật mà không cần viết lại toàn bộ hệ thống.
