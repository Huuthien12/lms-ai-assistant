# Thiết kế benchmark nhiều LLM

## Phạm vi

Benchmark dùng lại retrieval và ranh giới tin cậy hiện có. Nó không tạo endpoint, dashboard, bảng SQL hoặc cơ chế retrieval mới; không xóa/reindex KB. AI Tutor vẫn mặc định dùng Ollama `qwen2.5:3b` với `top_k=3`.

Luồng được tách thành:

```text
Moodle authorization
  -> publication ACTIVE
  -> verified retrieval context
  -> GroundedChatService.prepare()       (chạy một lần)
  -> PreparedGroundedPrompt bất biến
       -> Ollama
       -> OpenAI
       -> Gemini
       -> Anthropic
  -> BenchmarkRecord riêng cho từng model
```

`PreparedGroundedPrompt` giữ nguyên prompt, system prompt, nguồn đã chọn, chunk IDs, document versions, prompt version và retrieval config. `BenchmarkRunner` truyền đúng hai chuỗi prompt đó cho mọi target; provider không được retrieval lại.

## Tái sử dụng DeepTutor

DeepTutor đã có:

- `LLMConfig` và `GenerationSettings`;
- provider registry cho `ollama`, `openai`, `gemini`, `anthropic`;
- OpenAI-compatible adapter cho Ollama/OpenAI/Gemini;
- native Anthropic adapter;
- chuẩn hóa usage, retry và đặc điểm token limit theo model.

FastAPI LMS không import trực tiếp runtime này vì DeepTutor dùng venv và dependency riêng. `DeepTutorProvider` gọi một JSON worker bằng Python trong `DeepTutor/.venv`, tương tự cầu nối retrieval hiện hữu. Worker chỉ nhận tên biến môi trường chứa key, không nhận giá trị key. Nó tạo provider qua `get_runtime_provider()` của DeepTutor.

## Cấu hình chung

`ModelConfig` gồm:

| Trường | Ý nghĩa |
| --- | --- |
| `provider`, `model` | Định danh target |
| `temperature`, `max_tokens`, `timeout_seconds` | Tham số generation chung |
| `api_key_env` | Tên biến môi trường, không phải secret |
| `base_url` | Endpoint tùy chọn; bỏ trống để dùng mặc định registry |
| `allow_cloud_document_content` | Cổng cho phép gửi evidence lên cloud, mặc định `False` |
| `input_cost_per_million`, `output_cost_per_million` | Giá do người chạy benchmark cung cấp; bỏ trống thì cost là `null` |

Ví dụ cấu hình target, chưa thực hiện request:

```python
ModelConfig("ollama", "qwen2.5:3b")
ModelConfig("openai", "gpt-model", api_key_env="OPENAI_API_KEY",
            allow_cloud_document_content=True)
ModelConfig("gemini", "gemini-model", api_key_env="GEMINI_API_KEY",
            allow_cloud_document_content=True)
ModelConfig("anthropic", "claude-model", api_key_env="ANTHROPIC_API_KEY",
            allow_cloud_document_content=True)
```

Key chỉ được đọc từ environment trong worker. `.env.example` chỉ khai báo tên biến trống. Không có key, prompt hay nội dung tài liệu trong command line, log hoặc benchmark metadata.

Hai cổng độc lập chặn cloud:

1. `BenchmarkRunner` không gọi provider cloud khi `allow_cloud_document_content=False`.
2. `DeepTutorProvider` kiểm tra lại trước khi tạo worker và kiểm tra key tồn tại.

Mặc định ứng dụng không cấu hình target cloud và vẫn chạy Ollama local.

## Bản ghi benchmark

Mỗi `BenchmarkRecord` có:

- `question_id`, `model`, `provider`, `prompt_version`;
- `document_version`, `retrieval_config`, `chunk_ids`;
- `latency` (milliseconds), `token_usage`, `estimated_cost`;
- `raw_response`, `displayed_answer`, `evaluation_result`;
- `status`, `error_code` để phân biệt lỗi API với câu trả lời chất lượng thấp.

`raw_response` và `displayed_answer` là hai trường riêng. Evaluation hiện kiểm tra nhiều tín hiệu: provider thành công, output không rỗng, chữ Hán, và số nguồn hợp lệ. Chữ Hán không phải tiêu chí duy nhất. Đây là bộ kiểm tra kỹ thuật ban đầu, chưa phải đánh giá độ đúng học thuật.

Cost chỉ được tính khi người chạy cung cấp cả hai đơn giá và provider trả token usage. Không hardcode bảng giá vì giá/model thay đổi theo thời gian.

## Cấu hình `top_k`

- AI Tutor: `AI_TUTOR_TOP_K=3` trong environment, giữ mặc định hiện tại.
- Benchmark hoặc test: truyền `top_k` vào `GroundedChatService.prepare()` để tạo snapshot khác.
- `retrieval_config` lưu `top_k`, số ứng viên đầu vào và số chunk được chọn.

Giá trị này điều khiển số chunk đã xác minh đưa vào prompt. LlamaIndex vẫn truy xuất tối đa 5 ứng viên cho mỗi publication như trước, nên không thay đổi index hoặc giao thức publication.

## Chạy benchmark bằng CLI

CLI xác minh token Moodle trực tiếp, chỉ đọc publication `ACTIVE`, rồi giữ cùng một retrieval lease trong khi gửi một `PreparedGroundedPrompt` cho các model. Token được đọc qua tên biến môi trường, không được truyền trên command line hoặc ghi vào output.

Định dạng câu hỏi JSONL (mỗi dòng là một object):

```json
{"question_id":"int1339-q01","question":"Cấu trúc rẽ nhánh dùng để làm gì?","reference_answer":"...","reference_sources":[{"document_id":"...","document_version_id":"...","page":12}]}
```

Ba trường chuỗi `question_id`, `question`, `reference_answer` là bắt buộc và không được rỗng. `reference_sources` là danh sách object tùy chọn; CLI giữ nguyên trường này để đánh giá ngoại tuyến và không dùng nó làm evidence cho model.

PowerShell, chạy hai model Ollama local:

```powershell
$env:MOODLE_PERSONAL_TOKEN = '<personal token>'
$env:MOODLE_BASE_URL = 'http://127.0.0.1:8088'
lms-dlu-demo\venv\Scripts\python.exe -m backend.services.ai.benchmark_cli `
  --input .\benchmark\questions.jsonl `
  --output .\benchmark\results.jsonl `
  --course INT1339 `
  --ollama-model qwen2.5:3b `
  --ollama-model llama3.2:3b `
  --top-k 3
```

Tiếp tục một lần chạy bị ngắt bằng cùng câu lệnh và thêm `--resume`. Khóa duy nhất là `question_id + provider + model`; CLI bỏ qua target đã có và từ chối output đang có nếu không chỉ định `--resume`.

Cloud dùng `--cloud-model openai:<model>`, `gemini:<model>` hoặc `anthropic:<model>`. Mỗi target cloud yêu cầu cả `--allow-cloud-document-content` và API key tương ứng trong `OPENAI_API_KEY`, `GEMINI_API_KEY` hoặc `ANTHROPIC_API_KEY`. Không có opt-in thì CLI dừng trước retrieval/provider call.

Mỗi dòng output mở rộng `BenchmarkRecord` bằng câu hỏi và đáp án tham chiếu, `retrieval_context_id`, metadata `sources`, và `generation_config`. Output không chứa token Moodle, API key, tên biến API key, prompt đầy đủ hoặc nội dung chunk thô. `latency` dùng milliseconds.

Đánh giá tách ba trạng thái: `status` là kết quả gọi provider; `quality_status`/`evaluation_result` là chất lượng output; `display_action` cho biết giữ raw, dùng fallback hay để trống khi provider lỗi. Raw response luôn được giữ trong benchmark. Citation chấp nhận `[Nguồn 1]`, `[Nguồn: 1]`, `[Nguồn #1]` và danh sách như `[Nguồn 1, 2]`; `citation_status` phân biệt `missing`, `invalid`, `valid` và `not_required`.

Một vài ký tự Hán trong câu tiếng Việt được ghi nhận là cảnh báo và không bị xóa hoặc làm thay toàn bộ câu trả lời. Fallback chỉ áp dụng khi phần chữ Hán chiếm ưu thế, output rỗng, hoặc model làm lộ tên biến prompt nội bộ. Nguồn hiển thị vẫn do receipt retrieval đã xác minh cung cấp, không phụ thuộc model có sinh citation hay không. Prompt có thay đổi này mang version `grounded-chat-v3`; dùng file output mới khi so sánh với benchmark cũ.

CLI đọc input và file resume bằng `utf-8-sig` để chấp nhận UTF-8 có hoặc không có BOM trên Windows. Output luôn ghi UTF-8 không BOM với `ensure_ascii=False`.

## Chưa triển khai

- Endpoint và dashboard benchmark.
- Batch scheduler và kho SQL.
- Bảng giá tự động hoặc API pricing.
- Human grading, LLM-as-judge, semantic faithfulness hoặc kiểm tra đúng/sai theo đáp án chuẩn.
- Gọi thật OpenAI, Gemini, Anthropic.
- Secret manager cụ thể; interface hiện dùng environment và có thể được thay tại composition root sau.

Khi thêm endpoint, endpoint phải dùng cùng authorization dependency hiện hữu, tạo snapshot bên trong lease của `VerifiedPublicationService`, reauthorize trước và sau generation, và chỉ cho phép cloud bằng policy phía server; không nhận `allow_cloud_document_content` trực tiếp từ request của sinh viên.
