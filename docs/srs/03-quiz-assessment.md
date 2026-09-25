# 03 — QUIZ & ASSESSMENT

## 1. Mục tiêu
Biến kiến thức trong DeepTutor KB thành hoạt động kiểm tra có kiểm soát và tạo vòng lặp:
`Học → Quiz → Chấm → Phát hiện sai → Retrieval → Giải thích → Ôn lại`.

Quiz AI trong prototype phục vụ tự học, không mặc định là bài thi chính thức.

## 2. Quiz types
P1:
- Multiple Choice (single answer).
- True/False.
P2:
- Multiple-select.
- Short answer có rubric/semantic evaluation.

Ưu tiên MCQ để chấm deterministic.

## 3. Input tạo quiz
```json
{
  "student_id": "SV001",
  "course_id": "INT1234",
  "topic": "Deadlock",
  "question_count": 10,
  "difficulty": "medium",
  "question_types": ["mcq"]
}
```

Validation:
- student enrol course;
- KB READY;
- `question_count` trong giới hạn, đề xuất 5–20;
- difficulty ∈ easy|medium|hard|mixed;
- topic optional nhưng phải thuộc/khớp tài liệu retrieval, không tin chuỗi topic là nguồn tri thức.

## 4. Generation flow
```text
Student
 -> Backend
 -> validate enrolment
 -> course -> KB
 -> DeepTutor retrieval theo topic/coverage
 -> retrieved chunks + source metadata
 -> AI Orchestrator
 -> Quiz schema
 -> validate schema
 -> persist Quiz + Questions + Options
 -> return quiz WITHOUT correct answers
```

## 5. Quy tắc bảo mật đáp án
Endpoint lấy quiz cho student không được trả:
- `is_correct`;
- `correct_option_id`;
- hidden explanation/rubric trước submit.

Đáp án đúng chỉ ở server/DB.

## 6. Quiz schema
```json
{
  "title": "Ôn tập Deadlock",
  "course_id": "INT1234",
  "difficulty": "medium",
  "questions": [
    {
      "question_id": "...",
      "type": "mcq",
      "question": "...",
      "options": [
        {"id":"A","text":"..."},
        {"id":"B","text":"..."},
        {"id":"C","text":"..."},
        {"id":"D","text":"..."}
      ],
      "correct_option_id": "B",
      "explanation": "...",
      "topic": "Deadlock",
      "source_refs": []
    }
  ]
}
```

## 7. Quality rules khi sinh quiz
- Không tạo câu hỏi ngoài context được retrieval.
- Mỗi MCQ có đúng một đáp án đúng.
- Distractors phải hợp lý nhưng không cố tình mơ hồ.
- Không hỏi dựa vào thông tin không có trong tài liệu.
- Không dùng “tất cả đáp án trên” ở P1 để giảm ambiguity.
- Không lặp cùng một câu dưới cách diễn đạt gần giống trong một quiz.
- Câu hỏi phải có topic label.
- Explanation phải phù hợp đáp án đúng.
- Source metadata không được bịa.
- Nếu retrieval không đủ để tạo đủ số câu, trả ít hơn kèm `partial=true` hoặc báo không đủ context theo contract.

## 8. Submit attempt
```json
{
  "attempt_id": "...",
  "answers": [
    {"question_id":"Q1","selected_option_id":"B"},
    {"question_id":"Q2","selected_option_id":"A"}
  ]
}
```

Rules:
- attempt phải thuộc student hiện tại;
- question phải thuộc quiz;
- một question chỉ có một final answer ở MCQ;
- sau submit, status = SUBMITTED/GRADED;
- không submit lại cùng attempt; muốn làm lại tạo attempt mới.

## 9. Auto grading
MCQ/TF:
```text
selected_option_id == correct_option_id -> correct
else -> incorrect
```
Score:
```text
score_percent = correct_count / total_questions * 100
```
Không dùng LLM để quyết định đúng/sai cho MCQ nếu đã có answer key.

## 10. Wrong-answer explanation
Với mỗi câu sai:
```text
question + selected answer + correct answer + topic
        |
        v
DeepTutor retrieve lại đúng course/topic
        |
        v
AI explanation prompt
        |
        v
why_wrong + why_correct + key_concept + source
```

Output:
```json
{
  "question_id":"Q4",
  "correct":false,
  "selected":"A",
  "correct_answer":"B",
  "explanation":"...",
  "key_concept":"Deadlock conditions",
  "sources":[]
}
```

Nếu retrieval không đủ căn cứ, không tạo lời giải giả vờ dựa trên tài liệu.

## 11. Result page
Hiển thị:
- score;
- correct/incorrect count;
- từng câu;
- đáp án student;
- đáp án đúng;
- explanation;
- nguồn nếu có;
- topic yếu;
- nút `Ôn lại`, `Tạo flashcards`, `Làm quiz khác`.

## 12. Topic statistics
Mỗi question gắn topic. Sau grading:
```text
topic_accuracy = correct_topic_questions / total_topic_questions
```
Dữ liệu này là input cho mastery; không tự kết luận tuyệt đối từ 1 câu.

## 13. States
```text
Quiz: DRAFT -> READY -> ARCHIVED
Attempt: CREATED -> IN_PROGRESS -> SUBMITTED -> GRADED
                     \-> ABANDONED (optional)
```

## 14. Acceptance criteria
- Quiz đúng course/KB.
- Student course A không lấy quiz từ B.
- Client không nhận answer key trước submit.
- Chấm MCQ deterministic.
- Câu sai có explanation grounded khi đủ context.
- Submit attempt hai lần bị chặn/idempotent.
- Lưu score + question results + topic stats.
- Provider fallback không làm mất schema.
