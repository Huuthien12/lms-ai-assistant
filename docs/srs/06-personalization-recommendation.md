# 06 — PERSONALIZATION & RECOMMENDATION

## 1. Mục tiêu
Dùng dữ liệu tiến độ để đề xuất hành động học tiếp theo, không chỉ sinh lời khuyên chung chung.

## 2. Inputs
```text
student_id
course_id
TopicMastery
recent QuizAttempts
wrong topics
flashcard feedback
course materials available
assignment/deadline (optional, nếu LMS cung cấp)
```

## 3. Recommendation types
- REVIEW_TOPIC
- RETAKE_QUIZ
- GENERATE_FLASHCARDS
- READ_MATERIAL
- TRY_HARDER_QUIZ
- CONTINUE_NEXT_TOPIC

## 4. Rule-first recommendation P1
Ưu tiên logic deterministic:
```text
mastery < 50 -> REVIEW_TOPIC + FLASHCARDS + EASY_QUIZ
50–69 -> REVIEW_TOPIC + MEDIUM_QUIZ
70–84 -> MEDIUM/HARD_QUIZ
>=85 -> NEXT_TOPIC hoặc HARD_QUIZ
```
LLM dùng để diễn đạt lời khuyên; không để LLM tự bịa mastery.

## 5. Adaptive quiz P2
Difficulty:
```text
WEAK -> easy-heavy
DEVELOPING -> easy/medium
GOOD -> medium/hard
MASTERED -> hard/application
```
Topic distribution ưu tiên topic yếu nhưng vẫn có một phần câu ôn topic tốt để tránh “học lệch”.

## 6. Study plan P2
Nếu Assignment/deadline có thật:
```text
deadline + weak topics + available materials
 -> deterministic plan inputs
 -> LLM turns them into readable plan
```
Không bịa deadline. Nếu Moodle chưa cung cấp deadline, không tạo ngày giả.

## 7. Explain-at-my-level
Chat action:
- Giải thích đơn giản hơn.
- Giải thích chi tiết.
- Cho ví dụ.
- Tạo flashcards.
- Kiểm tra tôi 5 câu.
Các action vẫn dùng course/KB hiện tại.

## 8. Guardrails
- Recommendation không được truy cập course student chưa enrol.
- Không gọi một topic là “yếu” nếu evidence quá ít mà không nêu confidence.
- Không tạo lời khuyên dựa trên dữ liệu không tồn tại.
- Không biến recommendation thành điểm chính thức.

## 9. Acceptance
- REC-01: weak topic tạo hành động ôn phù hợp.
- REC-02: mastered topic không bị ưu tiên vô lý.
- REC-03: dữ liệu ít → nêu chưa đủ bằng chứng.
- REC-04: LLM failure → vẫn có rule-based recommendation cơ bản.
- REC-05: deadline chỉ xuất hiện khi LMS trả dữ liệu thật.
