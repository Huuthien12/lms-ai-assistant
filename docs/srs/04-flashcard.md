# 04 — FLASHCARD

## 1. Mục tiêu
Sinh flashcard từ tài liệu course để hỗ trợ active recall sau khi học/chat/quiz.

## 2. Nguồn tạo
- toàn course;
- topic;
- material cụ thể nếu backend có mapping;
- các topic/câu sai từ quiz.

## 3. Flow
```text
Student -> course/topic
 -> DeepTutor retrieval
 -> context
 -> AI Orchestrator
 -> validate Flashcard schema
 -> save FlashcardSet/Cards
 -> review
 -> record feedback
```

## 4. Card schema
```json
{
  "front": "Bốn điều kiện cần của deadlock là gì?",
  "back": "...",
  "topic": "Deadlock",
  "difficulty": "medium",
  "source_refs": []
}
```

## 5. Rules
- Front ngắn, một ý chính.
- Back đủ để tự kiểm tra, không quá dài.
- Không tạo fact ngoài context.
- Tránh duplicate/near-duplicate.
- Không bịa page/source.
- Một set đề xuất 5–30 cards; giới hạn cấu hình được.
- Không để answer xuất hiện trực tiếp trong front.

## 6. Review feedback
P1 đơn giản:
```text
AGAIN
HARD
GOOD
EASY
```
Lưu feedback + timestamp. P1 chưa bắt buộc thuật toán spaced repetition hoàn chỉnh.

## 7. P2 scheduling
Có thể thêm:
```text
next_review_at
interval_days
ease_factor
review_count
```
Thuật toán cụ thể phải được tài liệu hóa nếu triển khai; không gọi là SM-2 nếu không thực sự theo SM-2.

## 8. Quiz-to-flashcard
Sau quiz:
- lấy topic sai;
- retrieve context;
- tạo set `Ôn lại sau Quiz <id>`;
- ưu tiên concepts student sai;
- không đưa nguyên câu quiz thành flashcard nếu không phù hợp.

## 9. Acceptance
- FC-01: tạo set đúng course.
- FC-02: không lộ dữ liệu course khác.
- FC-03: source hợp lệ nếu có.
- FC-04: feedback được lưu.
- FC-05: có thể tạo từ wrong topics.
- FC-06: malformed LLM output không được lưu.
