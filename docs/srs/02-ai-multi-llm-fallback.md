# 02 — AI MULTI-LLM FALLBACK

## 1. Mục tiêu
DeepSeek là provider chính. Khi không thể phục vụ vì quota/rate-limit/timeout/model unavailable hoặc lỗi tạm thời, AI Orchestrator có thể chuyển sang provider dự phòng mà không thay đổi API nghiệp vụ.

## 2. Phân biệt hai vấn đề token
### A. Quota/rate limit/provider capacity
Ví dụ API trả 429/quota exhausted. Có thể fallback provider.

### B. Context/token limit của request
Prompt + context quá dài. Không nên lập tức đổi model. Backend phải:
1. giảm số chunk/top-k;
2. loại context trùng;
3. cắt lịch sử không cần thiết;
4. tóm tắt lịch sử nếu có chiến lược;
5. retry một lần với context nhỏ hơn;
6. chỉ fallback nếu policy/model dự phòng hỗ trợ và việc fallback hợp lý.

Không mô tả hai trường hợp trên như cùng một lỗi.

## 3. Provider interface đề xuất
```python
class LLMProvider:
    async def generate(self, request) -> LLMResult: ...
    async def health_check(self) -> ProviderHealth: ...
```

`LLMResult` tối thiểu:
```text
status
provider
model
content
latency_ms
usage (nullable)
error_code (nullable)
```

## 4. Provider priority
```text
PRIMARY: DeepSeek
FALLBACK_1: configurable provider/model
FALLBACK_2: optional
```
Không hard-code tên fallback vào business logic. Cấu hình bằng env/config.

## 5. State machine
```text
REQUEST
  |
  v
Validate input/context
  |
  v
Call PRIMARY
  |---------------- SUCCESS ----------------> VALIDATE OUTPUT -> RETURN
  |
  +-- retryable error --> retry policy
                           |
                           +-- success ------> VALIDATE -> RETURN
                           |
                           +-- fail ---------> FALLBACK_1
                                                  |
                                +-----------------+----------------+
                                |                                  |
                             success                            retryable fail
                                |                                  |
                             validate                         FALLBACK_2?
                                |                                  |
                              return                         fail gracefully
```

## 6. Error taxonomy
### Retry/fallback candidates
- 429/rate limit/quota (theo response provider).
- timeout/network transient.
- 5xx/provider unavailable.
- model temporarily unavailable.
- empty response sau validation nếu policy cho phép.

### Không retry mù quáng
- 400 do request sai.
- authentication/invalid API key.
- authorization.
- malformed internal prompt contract do code.
- content/context vượt giới hạn mà chưa tối ưu request.
- dữ liệu người dùng không hợp lệ.

## 7. Retry policy đề xuất
- Tối đa 1 retry/provider cho lỗi transient trong prototype.
- Có backoff ngắn.
- Không retry vô hạn.
- Toàn bộ request có overall timeout.
- Sau khi fallback thành công, response ghi `fallback_used=true`.

## 8. Circuit breaker — P2
Nếu provider liên tục lỗi trong cửa sổ thời gian:
```text
CLOSED -> OPEN -> HALF_OPEN -> CLOSED
```
P0/P1 có thể chỉ log failure count; không bắt buộc triển khai circuit breaker đầy đủ.

## 9. Grounding invariant
Dù đổi model:
- context vẫn lấy từ cùng `course_id -> kb_name`;
- không fallback sang KB khác/default;
- prompt grounded vẫn áp dụng;
- nguồn chỉ lấy từ metadata thật;
- thiếu căn cứ → trả trạng thái không đủ thông tin.

## 10. Structured output
Các nghiệp vụ Quiz/Flashcard phải yêu cầu JSON/schema. Backend phải validate:
- đủ field;
- đúng số lượng;
- correct answer thuộc options;
- không duplicate ID;
- explanation không rỗng nếu bắt buộc;
- source reference chỉ dùng metadata có thật.

Malformed output:
1. thử repair/parse an toàn nếu rõ ràng;
2. có thể retry 1 lần với instruction chặt hơn;
3. fallback nếu policy cho phép;
4. nếu vẫn lỗi → không lưu object lỗi vào DB.

## 11. Logging
```text
request_id
feature = chat|quiz|flashcard|explanation|recommendation
course_id
kb_name
provider
model
attempt_no
fallback_used
fallback_reason
status
latency_ms
provider_error_code
usage_input_tokens?
usage_output_tokens?
```
Token usage chỉ lưu khi provider thực sự cung cấp hoặc hệ thống có cách đo hợp lệ; không tự bịa.

## 12. Security
`.env` ví dụ:
```text
DEEPSEEK_API_KEY=...
PRIMARY_LLM_PROVIDER=deepseek
PRIMARY_LLM_MODEL=...
FALLBACK_LLM_PROVIDER=...
FALLBACK_LLM_MODEL=...
LLM_TIMEOUT_SECONDS=...
LLM_MAX_RETRIES=1
```
Không commit key. Không trả raw key/error chứa secret cho frontend.

## 13. Acceptance criteria
- AC-AI-01: DeepSeek success → không gọi fallback.
- AC-AI-02: simulated 429 → fallback được gọi.
- AC-AI-03: fallback success → client vẫn nhận output hợp lệ và metadata cho biết fallback.
- AC-AI-04: tất cả provider fail → HTTP/business error thân thiện, backend không crash.
- AC-AI-05: invalid key → không retry/fallback vô hạn.
- AC-AI-06: context quá dài → áp dụng context reduction trước.
- AC-AI-07: fallback không đổi course/KB.
- AC-AI-08: log không chứa API key.
