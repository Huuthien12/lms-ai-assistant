# 05 — LEARNING PROGRESS & MASTERY

## 1. Mục tiêu
Tạo hồ sơ tiến độ theo `student + course + topic` từ bằng chứng học tập thực tế, không chỉ từ lịch sử chat.

## 2. Evidence
P1:
- quiz attempts;
- question correctness;
- flashcard review feedback.

P2:
- repeated attempts theo thời gian;
- completion/material interaction nếu LMS cung cấp;
- assignment data nếu contract Moodle đủ rõ.

Chat không nên tự động được coi là “đã thành thạo”.

## 3. Topic model
Mỗi quiz question/flashcard có `topic`. Topic có thể:
- do AI đề xuất nhưng backend normalize;
- hoặc lấy từ danh mục topic của course do teacher/config định nghĩa.

P1 nên dùng topic string chuẩn hóa; P2 có bảng `Topics`.

## 4. Mastery score đề xuất
Để tránh giả khoa học, P1 có thể dùng score đơn giản, minh bạch:
```text
quiz_accuracy = correct / answered
```
Nếu có flashcard:
```text
flashcard_score:
AGAIN=0.0
HARD=0.4
GOOD=0.75
EASY=1.0
```
Một công thức prototype có thể cấu hình:
```text
mastery = 0.8 * recent_quiz_accuracy + 0.2 * recent_flashcard_score
```
Chỉ dùng nếu có đủ dữ liệu tương ứng; nếu thiếu, dùng thành phần có dữ liệu và ghi `confidence`.

## 5. Levels
Ví dụ cấu hình:
```text
0–49   WEAK
50–69  DEVELOPING
70–84  GOOD
85–100 MASTERED
```
Đây là nhãn hỗ trợ học tập trong prototype, không phải đánh giá học thuật chính thức.

## 6. Confidence
```text
LOW    < 5 evidence items
MEDIUM 5–14
HIGH   >= 15
```
Ngưỡng phải cấu hình/tài liệu hóa. UI nên hiển thị “ít dữ liệu” khi LOW.

## 7. Update flow
```text
Quiz graded / Flashcard reviewed
 -> create LearningEvent
 -> aggregate by student/course/topic
 -> update TopicMastery
 -> recommendation engine reads mastery
```

## 8. Không giảm/ tăng mastery tùy tiện
- Không cộng điểm chỉ vì student mở tài liệu.
- Không coi một câu đúng là mastered.
- Không dùng câu hỏi course khác.
- Nếu quiz bị xóa, cần policy rõ ràng về historical evidence.

## 9. Dashboard
P2:
```text
Course INT1234
Process             90%  MASTERED
Thread              82%  GOOD
Synchronization     58%  DEVELOPING
Deadlock            42%  WEAK
```
Hiển thị số evidence và lần cập nhật cuối.

## 10. Acceptance
- LP-01: score chỉ lấy evidence đúng student/course.
- LP-02: grading xong cập nhật topic.
- LP-03: attempt mới có thể thay đổi mastery.
- LP-04: LOW confidence được thể hiện.
- LP-05: không dùng chat count làm mastery.
