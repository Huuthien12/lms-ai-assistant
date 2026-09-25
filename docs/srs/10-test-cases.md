# 10 — TEST CASES & ACCEPTANCE

## A. DeepTutor/LMS regression
| ID | Test | Expected |
|---|---|---|
| TC-001 | Upload PDF đầu tiên | Tạo đúng course KB, index |
| TC-002 | Upload PDF thứ hai | Add vào KB hiện tại |
| TC-003 | KB PROCESSING | Không chat/generate sai trạng thái |
| TC-004 | Cross-course retrieval | Không lấy tài liệu course khác |
| TC-005 | Student chưa enrol | 403 |
| TC-006 | Out-of-document | Không bịa theo tài liệu |

## B. Multi-LLM
| ID | Test | Expected |
|---|---|---|
| TC-AI-001 | DeepSeek success | Không gọi fallback |
| TC-AI-002 | DeepSeek 429 | Fallback được thử |
| TC-AI-003 | DeepSeek timeout | Retry/fallback theo policy |
| TC-AI-004 | DeepSeek 401 | Fail cấu hình; không loop |
| TC-AI-005 | Primary + fallback fail | 503/error thân thiện |
| TC-AI-006 | Fallback success | `fallback_used=true` |
| TC-AI-007 | Context quá dài | Reduce context trước |
| TC-AI-008 | Malformed quiz JSON | Validate/retry/fail, không lưu READY |
| TC-AI-009 | Provider failover | KB/course không đổi |
| TC-AI-010 | Log inspection | Không có API key |

## C. Quiz
| ID | Test | Expected |
|---|---|---|
| TC-QZ-001 | Generate 10 MCQ | Quiz READY, <= requested count hợp lệ |
| TC-QZ-002 | Topic không đủ context | Partial/error rõ ràng |
| TC-QZ-003 | GET quiz student | Không có correct answer |
| TC-QZ-004 | Submit 8/10 đúng | Score 80% |
| TC-QZ-005 | Submit lại attempt | Bị chặn/idempotent |
| TC-QZ-006 | Answer question ngoài quiz | Reject |
| TC-QZ-007 | Attempt của student khác | 403 |
| TC-QZ-008 | Question source | Source thật hoặc empty, không bịa |
| TC-QZ-009 | Duplicate generated question | Validator phát hiện/giảm duplicate |
| TC-QZ-010 | Correct option không tồn tại | Generation FAILED/retry |
| TC-QZ-011 | Wrong answer | Có explanation grounded |
| TC-QZ-012 | Explanation retrieval thiếu | Báo không đủ căn cứ |

## D. Flashcard
| ID | Test | Expected |
|---|---|---|
| TC-FC-001 | Generate 10 cards | Set READY |
| TC-FC-002 | Cross-course | Không lẫn course |
| TC-FC-003 | AGAIN/HARD/GOOD/EASY | Review được lưu |
| TC-FC-004 | From wrong topics | Cards ưu tiên topic sai |
| TC-FC-005 | Malformed output | Không lưu card lỗi |

## E. Progress
| ID | Test | Expected |
|---|---|---|
| TC-LP-001 | Quiz graded | Learning events tạo |
| TC-LP-002 | Multiple questions same topic | Accuracy aggregate đúng |
| TC-LP-003 | Student khác | Progress độc lập |
| TC-LP-004 | Course khác | Progress độc lập |
| TC-LP-005 | Ít evidence | Confidence LOW |
| TC-LP-006 | New attempt improves | Mastery cập nhật theo formula |

## F. Recommendation
| ID | Test | Expected |
|---|---|---|
| TC-REC-001 | Weak topic | Recommend review/easy quiz |
| TC-REC-002 | Mastered topic | Không ưu tiên ôn cơ bản |
| TC-REC-003 | No evidence | Nêu chưa đủ dữ liệu |
| TC-REC-004 | LLM unavailable | Rule-based recommendation vẫn chạy |
| TC-REC-005 | No LMS deadline | Không bịa deadline |

## G. Security
| ID | Test | Expected |
|---|---|---|
| TC-SEC-001 | Student gọi teacher upload | 403 |
| TC-SEC-002 | Student đọc attempt khác | 403 |
| TC-SEC-003 | Client gửi kb_name giả | Backend bỏ qua/tự map |
| TC-SEC-004 | API key scan repo | Không có key |
| TC-SEC-005 | Error response | Không lộ stack/secret |

## H. End-to-end demo acceptance
1. Teacher/course có tài liệu.
2. Tài liệu sync đúng KB và READY.
3. Student enrol course đăng nhập.
4. Student chat, DeepTutor retrieval đúng tài liệu.
5. DeepSeek trả lời.
6. Mô phỏng primary 429 và chứng minh fallback.
7. Student tạo quiz 5–10 câu.
8. Student cố ý trả lời sai một số câu.
9. Hệ thống chấm điểm.
10. DeepTutor retrieve lại context cho câu sai.
11. AI giải thích vì sao sai + kiến thức đúng + nguồn nếu có.
12. Student tạo flashcards từ topic sai.
13. Progress/mastery cập nhật (nếu P2 hoàn thành).
14. Recommendation chỉ ra nội dung nên ôn (nếu P2 hoàn thành).

## Definition of Done cho test
Mỗi case cần:
`ID, precondition, input, steps, expected, actual, PASS/FAIL, evidence/screenshot/log`.
