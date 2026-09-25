# DeepTuTor — Bộ SRS mở rộng

## Đề tài
**Tìm hiểu DeepTutor và xây dựng ứng dụng minh họa tích hợp dữ liệu từ LMS**

Bộ tài liệu này mở rộng SRS hiện tại theo hướng **trợ lý học tập AI khép kín**:

`Moodle/LMS → DeepTutor/RAG → Multi-LLM → Chat/Quiz/Flashcard → Chấm điểm → Giải thích câu sai → Learning Progress → Cá nhân hóa`

## Mục tiêu
1. Giữ nguyên kiến trúc lõi: LMS cung cấp ngữ cảnh; DeepTutor quản lý KB/RAG; AI/LLM sinh nội dung; Backend điều phối.
2. DeepSeek là LLM chính, có cơ chế fallback sang model dự phòng khi quota/rate-limit/timeout/model unavailable.
3. Sinh quiz và flashcard phải grounded theo tài liệu đúng môn.
4. Sau quiz, hệ thống tự chấm, phân tích câu sai, truy xuất lại tài liệu bằng DeepTutor và giải thích.
5. Lưu tiến độ theo topic để hỗ trợ ôn tập cá nhân hóa.
6. Thiết kế đủ tổng quát để thay provider/model mà không sửa toàn bộ nghiệp vụ.

## Tài liệu
- [`PHAN_CONG_NHOM.md`](PHAN_CONG_NHOM.md): tài liệu ownership chính thức của 3 thành viên và ranh giới trách nhiệm DeepTutor, LMS/Moodle, AI.
- `01-system-overview.md`: phạm vi, kiến trúc, actors, use cases, ưu tiên.
- `02-ai-multi-llm-fallback.md`: DeepSeek + fallback, retry, quota, token/context.
- `03-quiz-assessment.md`: sinh quiz, làm bài, chấm điểm, giải thích câu sai.
- `04-flashcard.md`: tạo và ôn flashcard.
- `05-learning-progress-mastery.md`: tiến độ và mức độ thành thạo.
- `06-personalization-recommendation.md`: adaptive quiz, gợi ý học.
- `07-database-design.md`: mô hình dữ liệu mở rộng.
- `08-api-contracts.md`: API nội bộ đề xuất.
- `09-business-rules.md`: business rules và state transitions.
- `10-test-cases.md`: test cases/acceptance.
- `11-implementation-plan.md`: phân công 3 thành viên và kế hoạch triển khai.

## Quy tắc phạm vi
### P0 — bắt buộc
LMS/Course/User/Enrolment, PDF → KB, DeepTutor RAG đúng course, chat grounded, DeepSeek, Multi-LLM fallback, quyền cơ bản, error handling.

### P1 — mục tiêu demo
Quiz grounded, auto grading, giải thích câu sai có nguồn, flashcard, lưu attempts/progress.

### P2 — nâng cao
Topic mastery, adaptive quiz, recommendation, dashboard analytics.

Không triển khai P2 nếu P0/P1 chưa ổn định.
