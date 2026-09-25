# 08 — API CONTRACTS

## 1. Quy ước chung
Response lỗi:
```json
{
  "status": "error",
  "code": "AI_PROVIDER_UNAVAILABLE",
  "message": "Dịch vụ AI tạm thời không khả dụng.",
  "request_id": "..."
}
```
Không trả stack trace/secret cho client.

## 2. Chat
### POST `/chat`
```json
{
  "student_id":"SV001",
  "course_id":"INT1234",
  "message":"Deadlock là gì?"
}
```
Response:
```json
{
  "status":"success",
  "answer":"...",
  "course_id":"INT1234",
  "kb_name":"lms-int1234",
  "sources":[],
  "ai":{
    "provider":"deepseek",
    "model":"...",
    "fallback_used":false
  }
}
```

## 3. Generate quiz
### POST `/courses/{course_id}/quizzes`
```json
{
  "student_id":"SV001",
  "topic":"Deadlock",
  "question_count":10,
  "difficulty":"medium",
  "question_types":["mcq"]
}
```
Response không chứa answer key:
```json
{
  "quiz_id":"...",
  "status":"ready",
  "title":"Ôn tập Deadlock",
  "questions":[
    {
      "question_id":"Q1",
      "type":"mcq",
      "question":"...",
      "options":[
        {"id":"A","text":"..."},
        {"id":"B","text":"..."}
      ]
    }
  ]
}
```

## 4. Start/retrieve attempt
### POST `/quizzes/{quiz_id}/attempts`
Server lấy student từ auth trong bản hoàn thiện; prototype có thể truyền ID nhưng backend vẫn validate.

## 5. Submit quiz
### POST `/quiz-attempts/{attempt_id}/submit`
```json
{
  "answers":[
    {"question_id":"Q1","selected_option_id":"B"}
  ]
}
```
Response:
```json
{
  "attempt_id":"...",
  "status":"graded",
  "score_percent":80,
  "correct_count":8,
  "total_questions":10,
  "results":[
    {
      "question_id":"Q1",
      "correct":false,
      "selected_option_id":"A",
      "correct_option_id":"B",
      "explanation_status":"ready"
    }
  ]
}
```

## 6. Wrong-answer explanation
### GET `/quiz-attempts/{attempt_id}/review`
Chỉ owner/student được xem attempt của mình.
```json
{
  "score_percent":80,
  "weak_topics":["Deadlock"],
  "questions":[
    {
      "question_id":"Q1",
      "correct":false,
      "explanation":"...",
      "key_concept":"...",
      "sources":[]
    }
  ]
}
```

## 7. Flashcards
### POST `/courses/{course_id}/flashcard-sets`
```json
{
  "student_id":"SV001",
  "topic":"Deadlock",
  "count":15,
  "source_type":"topic"
}
```

### GET `/flashcard-sets/{set_id}`
Owner + enrolment validation.

### POST `/flashcards/{flashcard_id}/reviews`
```json
{"rating":"GOOD"}
```

## 8. Progress
### GET `/courses/{course_id}/progress`
```json
{
  "student_id":"SV001",
  "course_id":"INT1234",
  "topics":[
    {
      "topic":"Deadlock",
      "mastery_score":42,
      "level":"WEAK",
      "confidence":"MEDIUM",
      "evidence_count":7
    }
  ]
}
```

## 9. Recommendations
### GET `/courses/{course_id}/recommendations`
```json
{
  "recommendations":[
    {
      "type":"REVIEW_TOPIC",
      "topic":"Deadlock",
      "reason":"Kết quả gần đây ở topic này còn thấp.",
      "actions":["GENERATE_FLASHCARDS","EASY_QUIZ"]
    }
  ]
}
```

## 10. Provider health — admin/dev
### GET `/internal/ai/providers`
Không trả API key.
```json
{
  "providers":[
    {"name":"deepseek","status":"available"},
    {"name":"fallback","status":"available"}
  ]
}
```

## 11. Status codes đề xuất
- 200 success.
- 201 created.
- 400 invalid input.
- 401 unauthenticated.
- 403 not enrolled/not owner/not teacher.
- 404 resource/KB/quiz not found.
- 409 KB processing / attempt already submitted / conflict.
- 422 AI structured output invalid (nếu không recover).
- 429 application-level throttling nếu có.
- 502/503 upstream AI/DeepTutor unavailable.
- 504 upstream timeout.
