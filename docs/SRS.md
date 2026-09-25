# SOFTWARE REQUIREMENTS SPECIFICATION — DeepTuTor LMS AI

## 1. Tên đề tài
**Tìm hiểu DeepTutor và xây dựng ứng dụng minh họa tích hợp dữ liệu từ LMS**

## 2. Phiên bản mở rộng
SRS này kế thừa yêu cầu lõi của kế hoạch hiện tại và mở rộng theo định hướng:
- DeepSeek là LLM chính;
- Multi-LLM fallback;
- Quiz grounded;
- auto grading;
- giải thích câu sai bằng RAG;
- flashcards;
- learning progress/mastery;
- personalization/recommendation.

Chi tiết được chuẩn hóa trong thư mục `srs/`.

## 3. Product vision
Không chỉ xây chatbot. Sản phẩm mục tiêu là một vòng lặp học tập:
```text
LMS knowledge
 -> DeepTutor KB/RAG
 -> AI tutoring
 -> Quiz/Flashcard
 -> Student attempt
 -> Assessment
 -> Wrong-answer explanation
 -> Progress
 -> Personalized next action
```

## 4. Quy tắc không được phá
1. LMS là nguồn user/course/resource.
2. DeepTutor là lớp KB/retrieval/RAG.
3. Backend map course → KB.
4. AI chỉ sinh nội dung từ context khi feature yêu cầu grounded.
5. Không cross-course.
6. Không bịa source.
7. Không để provider/model quyết định authorization.
8. Fallback model không đồng nghĩa fallback knowledge base.
9. Quiz answer key không lộ trước submit.
10. Mastery/recommendation là hỗ trợ tự học, không mặc định là điểm chính thức.

## 5. Requirements map
| Group | IDs | Tài liệu |
|---|---|---|
| Core LMS/RAG | FR-01..FR-15 | SRS gốc + 01 |
| AI Provider | FR-16..FR-17 | 02 |
| Quiz | FR-18..FR-21 | 03 |
| Flashcard | FR-22 | 04 |
| Progress | FR-23 | 05 |
| Personalization | FR-24 | 06 |
| Observability | FR-25 | 02/07 |
| DB | DB-* | 07 |
| API | API-* | 08 |
| Business rules | BR-* | 09 |
| Tests | TC-* | 10 |
| Delivery | M0..M4 | 11 |

## 6. Priority
### P0
Core LMS/DeepTutor/RAG + DeepSeek + automatic fallback.

### P1
Quiz + grading + wrong-answer explanation + flashcard + persistence.

### P2
Mastery + adaptive quiz + recommendation + analytics.

## 7. Acceptance cấp hệ thống
Sản phẩm được xem là đạt mục tiêu mở rộng khi demo được ít nhất:
- course/material → đúng KB;
- grounded chat;
- primary LLM hoạt động;
- mô phỏng primary failure → fallback;
- grounded quiz;
- submit + deterministic grading;
- explanation cho câu sai có retrieval;
- flashcards;
- không cross-course;
- không lộ answer key/secret;
- backend không crash khi upstream lỗi.

## 8. Tài liệu chi tiết
Xem `README.md` và `srs/01` đến `srs/11`.
