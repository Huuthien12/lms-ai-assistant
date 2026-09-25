# 11 — IMPLEMENTATION PLAN & PHÂN CÔNG

## 1. Phân công giữ đúng chuyên môn

### Lương Hữu Thiện — DeepTutor/RAG/Integration
Chịu trách nhiệm:
- course → KB mapping;
- KB lifecycle;
- retrieval API/service;
- retrieval cho Chat;
- retrieval cho Quiz Generator;
- retrieval cho Wrong-answer Explanation;
- retrieval cho Flashcard;
- source metadata;
- cross-course isolation;
- integration FastAPI ↔ DeepTutor;
- hỗ trợ schema/DB integration chung.

Deliverables:
```text
backend/services/deeptutor_service.py
backend/services/retrieval_service.py
tests/deeptutor/
docs/deeptutor/
```

### Nguyễn Hồng Phúc Thọ — LMS/Moodle
Chịu trách nhiệm:
- Moodle local;
- User/Course/Role/Enrolment;
- Resource/File;
- Assignment/deadline nếu đủ thời gian;
- Moodle Web Services/REST;
- sync tài liệu;
- permission mapping;
- course/material metadata cho DeepTutor;
- kiểm thử quyền student/teacher.

Deliverables:
```text
backend/services/moodle_service.py
tests/moodle/
docs/moodle/
```

### Hoàng Bình Quân — AI/LLM
Chịu trách nhiệm:
- DeepSeek provider;
- provider interface;
- fallback provider;
- AI Orchestrator;
- prompt grounded;
- structured output;
- Quiz Generator;
- Flashcard Generator;
- Wrong-answer Explanation prompt;
- AI evaluation/error handling.

Deliverables:
```text
backend/services/ai/
    provider_base.py
    deepseek_provider.py
    fallback_provider.py
    orchestrator.py
    quiz_generator.py
    flashcard_generator.py
    explanation_service.py
tests/ai/
docs/ai/
```

### Phần chung
- DB migrations/models.
- API contracts.
- auth integration.
- progress/mastery.
- integration tests.
- README/demo/slides.

## 2. Kiến trúc code đề xuất
```text
backend/
  api/
    chat.py
    quizzes.py
    flashcards.py
    progress.py
  services/
    moodle_service.py
    deeptutor_service.py
    retrieval_service.py
    chat_service.py
    quiz_service.py
    flashcard_service.py
    grading_service.py
    progress_service.py
    recommendation_service.py
    ai/
      provider_base.py
      deepseek_provider.py
      fallback_provider.py
      orchestrator.py
  repositories/
  models/
  schemas/
  config/
tests/
  deeptutor/
  moodle/
  ai/
  quiz/
  flashcard/
  integration/
docs/
```

## 3. Kế hoạch 8 phiên

### Phiên 1 — Freeze SRS
Cả nhóm:
- review SRS;
- chốt P0/P1/P2;
- chốt API/DB;
- tạo issues/branches.

Thiện: xác minh DeepTutor CLI/KB.
Thọ: xác minh Moodle API.
Quân: xác minh DeepSeek API + provider prototype.

### Phiên 2 — Service abstraction
Thiện: `deeptutor_service`, retrieval contract.
Thọ: `moodle_service`, course/resource.
Quân: `LLMProvider`, `DeepSeekProvider`, structured result.

### Phiên 3 — Fallback + integration core
Quân: orchestrator/fallback/error taxonomy.
Thiện: chat retrieval/source metadata.
Thọ: material sync.
Cả nhóm: `/chat` end-to-end.

**Milestone M1:** P0 Chat + RAG + DeepSeek + fallback chạy.

### Phiên 4 — Quiz generation
Thiện: retrieval cho quiz.
Quân: quiz prompt/schema/validator.
Phần chung: DB Quiz/Question/Option.
API: create/get quiz.

### Phiên 5 — Attempts + grading + explanation
DB Attempt/Answer.
Grading deterministic.
Thiện: retrieval cho wrong answer.
Quân: explanation prompt.
API submit/review.

**Milestone M2:** Student làm quiz và được giải thích câu sai.

### Phiên 6 — Flashcards
Retrieval → generator → DB → review feedback.
Liên kết wrong topics → flashcard set.

**Milestone M3:** P1 hoàn thành.

### Phiên 7 — Progress/Personalization
Nếu P0/P1 ổn:
- LearningEvent;
- TopicMastery;
- rule-based recommendation;
- adaptive difficulty optional.

### Phiên 8 — Hardening & demo
- test suite;
- security;
- fallback simulation;
- cross-course tests;
- screenshots/log;
- README;
- sequence diagrams;
- slide/demo script.

## 4. Branches
```text
main
├─ feature/deeptutor-thien
├─ feature/moodle-tho
├─ feature/ai-quan
├─ feature/quiz-integration
└─ feature/progress-personalization
```
Không để branch integration kéo dài quá lâu; PR nhỏ, test trước merge.

## 5. Integration contracts bắt buộc
### Moodle → DeepTutor
```text
course_id
material_id
file_path/bytes/url
file_hash
```

### DeepTutor → AI
```text
course_id
kb_name
retrieved_context
source_metadata
```

### AI → Quiz service
Validated Quiz DTO/schema.

### Quiz → Progress
```text
student_id
course_id
topic
is_correct
attempt_id
timestamp
```

## 6. Milestones
### M0
SRS + contracts freeze.

### M1 — Core assistant
Moodle/LMS → KB → RAG → DeepSeek + fallback → answer.

### M2 — Assessment loop
Generate quiz → attempt → grade → explain wrong answers.

### M3 — Review loop
Flashcards from course/wrong topics.

### M4 — Personalization
Progress/mastery/recommendation.

## 7. Demo script
1. Teacher/student/course đã có sẵn.
2. Show PDF course và KB READY.
3. Student hỏi câu → answer + source.
4. Simulate DeepSeek 429 → show fallback log/provider.
5. Generate quiz.
6. Làm quiz, cố ý sai.
7. Submit → score.
8. Mở review → AI giải thích câu sai dựa trên RAG.
9. Generate flashcards từ weak topic.
10. Show progress/recommendation nếu đã làm P2.

## 8. Tiêu chí dừng scope
Nếu thiếu thời gian:
- Không làm dashboard đẹp trước khi quiz/explanation chạy.
- Không làm spaced repetition phức tạp trước flashcard basic.
- Không làm adaptive quiz trước deterministic quiz.
- Không làm nhiều fallback providers trước khi 1 primary + 1 fallback chạy ổn.
- Không refactor toàn bộ Moodle ngoài phần cần cho integration.
