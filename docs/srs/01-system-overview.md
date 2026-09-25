# 01 — SYSTEM OVERVIEW

## 1. Mục tiêu hệ thống
Xây dựng trợ lý học tập AI tích hợp LMS/Moodle và DeepTutor, hỗ trợ sinh viên:
- học từ tài liệu đúng môn;
- hỏi đáp có RAG;
- tự kiểm tra bằng quiz;
- ôn tập bằng flashcard;
- nhận giải thích cho câu trả lời sai;
- theo dõi tiến độ học;
- nhận gợi ý nội dung nên ôn.

Hệ thống không huấn luyện LLM từ đầu và không thay thế giảng viên.

## 2. Kiến trúc logic

```text
Moodle/LMS
 User | Course | Enrolment | Resource | Assignment
                     |
                     v
              FastAPI Backend
                     |
       +-------------+-------------+
       |                           |
       v                           v
 SQL Server                    DeepTutor
                                   |
                           Course -> KB
                                   |
                              Retrieval
                                   |
                             RAG Context
                                   |
                                   v
                          AI Orchestrator
                       /                  \
                 DeepSeek              Fallback LLM
                       \                  /
                        +-------+--------+
                                |
              +-----------------+----------------+
              |                 |                |
             Chat              Quiz          Flashcard
              |                 |                |
              +-----------------+----------------+
                                |
                           Student Action
                                |
                         Quiz Auto Grading
                                |
                    Wrong-answer Explanation
                                |
                          Learning Progress
                                |
                       Recommendation/Review
```

## 3. Nguyên tắc kiến trúc
- `course_id` do backend map sang `kb_name`; frontend không được tự chọn KB.
- Một course dùng một KB trong prototype.
- DeepTutor chịu trách nhiệm KB/index/retrieval/RAG.
- AI Orchestrator chịu trách nhiệm chọn provider/model, retry/fallback và chuẩn hóa output.
- Quiz/flashcard/explanation phải dùng context của đúng course.
- Fallback LLM không được làm mất quy tắc grounded.
- Không coi model fallback là fallback KB: KB vẫn phải đúng course.
- API key chỉ ở server-side `.env`/secret store.
- Mọi attempt, provider error và kết quả quan trọng phải có trace/log nhưng không log secret.

## 4. Actors
### ACT-01 Student
Đăng nhập; xem course; chat; tạo/làm quiz; xem kết quả; xem giải thích; tạo/ôn flashcard; xem tiến độ/gợi ý.

### ACT-02 Teacher
Quản lý tài liệu course; theo dõi sync/index; có thể xem thống kê tổng hợp nếu được bật. Không mặc định xem nội dung chat riêng tư nếu SRS chưa quy định.

### ACT-03 Admin
Cấu hình tích hợp, provider/model, trạng thái dịch vụ nếu prototype cần.

### ACT-04 Moodle/LMS
Nguồn User/Course/Enrolment/Resource/Assignment.

### ACT-05 DeepTutor
KB, indexing, retrieval, RAG context và source metadata.

### ACT-06 AI Orchestrator
Chọn model, fallback, validate structured output.

### ACT-07 LLM Provider
DeepSeek là primary; provider/model dự phòng do cấu hình.

## 5. Use cases chính
- UC-01 Login và xác thực role.
- UC-02 Chọn course đã enrol.
- UC-03 Teacher đồng bộ tài liệu → DeepTutor KB.
- UC-04 Student chat grounded.
- UC-05 Tạo quiz theo course/topic.
- UC-06 Làm quiz và submit.
- UC-07 Auto-grade.
- UC-08 Giải thích câu sai bằng RAG.
- UC-09 Tạo flashcards từ tài liệu.
- UC-10 Ghi nhận learning progress.
- UC-11 Sinh recommendation.
- UC-12 AI provider failover.

## 6. Functional requirements mở rộng
### FR-16 AI Provider Abstraction
Backend phải gọi AI qua interface/service thống nhất, không để endpoint gọi trực tiếp DeepSeek SDK/API ở nhiều nơi.

### FR-17 Automatic LLM Fallback
Khi primary provider gặp lỗi đủ điều kiện fallback, hệ thống thử provider dự phòng theo policy.

### FR-18 Quiz Generation
Student có thể yêu cầu quiz theo course, số câu, độ khó, loại câu và topic tùy chọn.

### FR-19 Quiz Grounding
Quiz phải được sinh từ context do DeepTutor retrieval cung cấp.

### FR-20 Quiz Submission
Hệ thống nhận toàn bộ answers của attempt, khóa attempt sau submit và chấm điểm.

### FR-21 Wrong-answer Explanation
Mỗi câu sai phải có thể được giải thích dựa trên retrieved context; không bịa nguồn.

### FR-22 Flashcard Generation
Sinh flashcard từ course/topic, lưu set và cards để ôn lại.

### FR-23 Learning Progress
Lưu kết quả theo course/topic từ quiz attempts và flashcard review.

### FR-24 Recommendation
Tạo gợi ý ôn tập dựa trên dữ liệu thực có; nếu dữ liệu chưa đủ phải nói rõ.

### FR-25 Provider Observability
Ghi provider/model/status/latency/fallback_reason/token usage nếu API thực sự trả metadata.

## 7. Non-functional requirements mở rộng
- NFR-06 Availability: lỗi một LLM không làm backend crash.
- NFR-07 Portability: thay provider qua config/service abstraction.
- NFR-08 Consistency: structured output phải được validate trước khi lưu.
- NFR-09 Privacy: không gửi dữ liệu không cần thiết sang LLM.
- NFR-10 Auditability: lưu nguồn, model/provider và request trace cần thiết.
- NFR-11 Graceful degradation: nếu AI không dùng được, chức năng LMS/KB vẫn hiển thị trạng thái rõ ràng.
- NFR-12 Cost control: giới hạn số câu quiz, context, retry và request đồng thời.

## 8. Out of scope
- Huấn luyện/fine-tune LLM từ đầu.
- Proctoring/chống gian lận thi chính thức.
- Dùng quiz AI làm điểm chính thức của Moodle nếu chưa được giảng viên duyệt.
- Chẩn đoán năng lực học tập mang tính tuyệt đối.
- Đồng bộ toàn bộ Moodle database.
