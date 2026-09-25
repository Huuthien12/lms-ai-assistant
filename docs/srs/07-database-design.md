# 07 — DATABASE DESIGN

## 1. Nguyên tắc
Giữ các bảng hiện tại `Users`, `Courses`, `Enrolments`, `Materials`, `ChatHistory`; mở rộng cho AI provider, quiz, flashcard và progress.

## 2. Bảng hiện có cần giữ
### Users
`user_id PK, username UNIQUE, password_hash, full_name, role, status`

### Courses
`course_id PK, course_code UNIQUE, course_name, status`

### Enrolments
`user_id FK, course_id FK, role, UNIQUE(user_id, course_id)`

### Materials
`material_id PK, course_id FK, file_name, file_path/moodle_file_ref, file_hash, uploaded_by, uploaded_at, sync_status, kb_name, sync_error`

### ChatHistory
Bổ sung optional:
`provider, model, fallback_used, latency_ms`.

## 3. AIRequestLog
```text
ai_request_id PK
request_id UNIQUE
student_id FK nullable
course_id FK nullable
feature
provider
model
attempt_no
fallback_used
fallback_reason nullable
status
error_code nullable
latency_ms
input_tokens nullable
output_tokens nullable
created_at
```
Không lưu secret/raw authorization header.

## 4. Quizzes
```text
quiz_id PK
course_id FK
created_by_student_id FK
title
topic nullable
difficulty
question_count
generation_status
provider nullable
model nullable
created_at
```

## 5. QuizQuestions
```text
question_id PK
quiz_id FK
type
question_text
topic
difficulty
correct_option_id
explanation
source_metadata JSON nullable
position
```

## 6. QuizOptions
```text
option_id PK
question_id FK
option_key
option_text
UNIQUE(question_id, option_key)
```

## 7. QuizAttempts
```text
attempt_id PK
quiz_id FK
student_id FK
status
started_at
submitted_at nullable
score_percent nullable
correct_count nullable
total_questions
```

## 8. QuizAnswers
```text
answer_id PK
attempt_id FK
question_id FK
selected_option_id nullable
is_correct nullable
answered_at
UNIQUE(attempt_id, question_id)
```

## 9. WrongAnswerExplanations
```text
explanation_id PK
answer_id FK UNIQUE
explanation_text
key_concept
source_metadata JSON nullable
provider
model
created_at
```

## 10. FlashcardSets
```text
flashcard_set_id PK
student_id FK
course_id FK
title
topic nullable
source_type
source_ref nullable
created_at
```

## 11. Flashcards
```text
flashcard_id PK
flashcard_set_id FK
front_text
back_text
topic
difficulty nullable
source_metadata JSON nullable
position
```

## 12. FlashcardReviews
```text
review_id PK
flashcard_id FK
student_id FK
rating
reviewed_at
next_review_at nullable
```

## 13. LearningEvents
Event ledger để audit:
```text
event_id PK
student_id FK
course_id FK
topic
event_type
reference_id
score_value nullable
created_at
```
`event_type`: QUIZ_ANSWER, QUIZ_ATTEMPT, FLASHCARD_REVIEW,...

## 14. TopicMastery
```text
mastery_id PK
student_id FK
course_id FK
topic
mastery_score
mastery_level
confidence_level
evidence_count
last_updated_at
UNIQUE(student_id, course_id, topic)
```

## 15. Recommendations
P2:
```text
recommendation_id PK
student_id FK
course_id FK
topic nullable
recommendation_type
reason
status
created_at
```

## 16. Quan hệ chính
```text
Course 1---N Materials
Course 1---N Quizzes
Quiz 1---N Questions
Question 1---N Options
Quiz 1---N Attempts
Attempt 1---N Answers
Answer 0---1 WrongAnswerExplanation

Student 1---N Attempts
Student 1---N FlashcardSets
FlashcardSet 1---N Flashcards
Flashcard 1---N Reviews

Student + Course + Topic -> TopicMastery
```

## 17. Constraints
- Cascade phải được cân nhắc; không xóa lịch sử học ngoài ý muốn.
- Answer key không trả qua student-facing GET.
- `source_metadata` chỉ chứa metadata thật.
- Topic cần normalize để tránh `Deadlock`, `dead lock`, `DEADLOCK` thành ba topic.
- `generation_status`: PENDING/GENERATING/READY/FAILED.
