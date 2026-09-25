# 09 — BUSINESS RULES

## Course/KB
- BR-01: 1 Course → 1 KB trong prototype.
- BR-02: frontend không truyền `kb_name` như nguồn tin cậy.
- BR-03: KB phải READY trước chat/quiz/flashcard retrieval.
- BR-04: không fallback sang default KB khi course KB lỗi.
- BR-05: cross-course retrieval bị cấm.

## AI provider
- BR-06: DeepSeek là primary theo cấu hình dự án.
- BR-07: fallback chỉ xảy ra theo error policy.
- BR-08: fallback provider nhận cùng grounded context contract.
- BR-09: auth/config error không retry vô hạn.
- BR-10: mọi provider fail → graceful error.
- BR-11: context-too-long phải được xử lý như request/context problem trước khi coi là quota fail.

## Quiz
- BR-12: chỉ student enrol course mới tạo/làm quiz.
- BR-13: quiz phải grounded theo KB course.
- BR-14: answer key không gửi trước submit.
- BR-15: MCQ chấm bằng key, không dùng LLM để “đoán” đúng sai.
- BR-16: attempt chỉ submit một lần.
- BR-17: câu sai có explanation khi context đủ.
- BR-18: explanation không được bịa source.
- BR-19: generated quiz malformed không lưu READY.
- BR-20: quiz AI là self-assessment trừ khi có yêu cầu khác của giảng viên.

## Flashcard
- BR-21: card grounded theo course.
- BR-22: feedback chỉ thuộc student owner.
- BR-23: không dùng flashcard review của student A cho mastery student B.

## Progress
- BR-24: mastery scope = student + course + topic.
- BR-25: chat count không đồng nghĩa mastery.
- BR-26: evidence ít phải có confidence thấp.
- BR-27: mastery không phải điểm chính thức.
- BR-28: recommendation đọc dữ liệu mastery, không tự bịa score.

## Security
- BR-29: backend enforce role/enrolment/ownership.
- BR-30: không hard-code secret.
- BR-31: không log token/password/API key.
- BR-32: student không đọc attempt/progress của student khác.
- BR-33: teacher access analytics phải theo phạm vi được quy định.

## Idempotency
- BR-34: material duplicate dùng hash/strategy chống index lặp.
- BR-35: submit attempt lặp không tạo grading lần hai.
- BR-36: retry AI không được tạo nhiều quiz READY cho cùng generation transaction nếu request idempotency được áp dụng.

## State transitions
```text
Material: PENDING -> PROCESSING -> READY
                         \-> FAILED
READY -> DELETED (sau sync strategy)

Quiz generation:
PENDING -> GENERATING -> READY
                    \-> FAILED

Attempt:
CREATED -> IN_PROGRESS -> SUBMITTED -> GRADED
```
State transition sai phải bị từ chối/log.
