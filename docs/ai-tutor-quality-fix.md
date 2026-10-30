# Bản sửa chất lượng AI Tutor — 18/10/2026

## Luồng thực tế

1. `lms-dlu-demo/app.py` gọi `render_verified_learning()` rồi `st.stop()`; phần giao diện demo cũ bên dưới không phải luồng đang chạy.
2. `verified_learning_ui.py` dùng `RealDeepTutorClient.request()` gửi câu hỏi tới `POST /learning/courses/{course_id}/chat`.
3. `verified_learning_router.py` xác minh scope và gọi `verified_chat.py`. Các endpoint `/lms/chat` và `/chat/grounded` cũng đi qua hàm này khi có publication service.
4. `VerifiedPublicationService.context()` chỉ lấy publication ACTIVE đúng scope; `DeepTutorFullSourceAdapter.retrieve()` gọi worker bằng môi trường DeepTutor.
5. `full_source_worker.py` dùng LlamaIndex vector retriever, `similarity_top_k=5` cho mỗi publication. Không dùng câu trả lời tổng hợp của DeepTutor làm bằng chứng.
6. `verify_raw_chunks()` kiểm tra chunk ID, hash, version, publication và manifest. `build_context()` chọn các chunk nguyên vẹn trong ngân sách 32.000 ký tự.
7. `GroundedChatService` tạo prompt, gọi `AIOrchestrator` rồi provider. Cấu hình hiện hữu trong `main.py` chọn Ollama, hoặc DeepSeek với fallback Ollama nếu đã cấu hình DeepSeek. Bản sửa không thay cấu hình này.
8. `verified_chat()` kiểm tra lại quyền, trả metadata do ứng dụng xác minh; giao diện hiển thị câu trả lời và nguồn. Lịch sử do learning router lưu theo scope.

## Nguyên nhân và bằng chứng

- Prompt cũ yêu cầu dựa vào tài liệu nhưng chưa quy định rõ tiếng Việt, độ ngắn, hoặc cách xử lý chỉ dẫn trong tài liệu. Chat cũng chưa đặt temperature hoặc giới hạn token riêng.
- Retriever luôn trả tối đa 5 ứng viên mỗi tài liệu. Trước đây các tài liệu được ghép theo thứ tự ledger, rồi áp ngân sách ký tự; đoạn tốt ở tài liệu sau có thể không được đưa vào context. Không có bước loại đoạn trùng trước prompt chat.
- Markdown hiện có của `Chuong 1.pdf` chứa bảng do bố cục slide, nhiều cột trống và `(cid:...)`. Tài liệu cùng chứa bài học về đệ quy và bài phép toán. Bài 10 ghi rõ dùng **lệnh rẽ nhánh** để kiểm tra `k`.
- `DocumentNormalizer` chuyển trực tiếp đầu ra MarkItDown sang artifact. Các mã CID là glyph PDF không giải mã được; chỉ đổi prompt không thể khôi phục chúng.
- Kiểm tra trực tiếp với `qwen2.5:3b` cho thấy system prompt đơn thuần chưa chặn được chỉ dẫn độc hại: mô hình từng trả lời bằng tiếng Trung, và sau khi đổi thứ tự prompt vẫn có thể nói sai bằng tiếng Việt. Vì vậy bản cuối có thêm bộ lọc override rõ ràng và kiểm tra chữ Hán ở đầu ra.

## File và thay đổi

| File | Thay đổi |
| --- | --- |
| `backend/services/ai/context_text.py` | Thêm làm sạch thận trọng và phát hiện các dạng ghi đè chỉ dẫn rõ ràng trong dữ liệu tham khảo. |
| `backend/services/ai/grounded_chat.py` | Bỏ chunk/tiêu đề có override rõ ràng; xếp theo điểm, loại nội dung trùng và giữ tối đa 3 chunk nguyên vẹn. Prompt JSON tách dữ liệu, câu hỏi và nhiệm vụ; ưu tiên tiếng Việt, thường 120–180 từ, không ghép nhầm bài tập, không đoán phần thiếu. Mặc định temperature 0,1 và max_tokens 1.024. Đầu ra có chữ Hán được thay bằng thông báo tiếng Việt an toàn, đánh dấu fallback. |
| `deeptutor_integration/verified_context.py` | Xếp hạng chung trước ngân sách ký tự; làm sạch preview sau xác minh, giữ nguyên nội dung/hash dùng kiểm chứng. Việc xếp hạng chung cũng áp dụng cho các chức năng học tập dùng context chung. |
| `lms-dlu-demo/verified_chat.py` | Trả đúng metadata của các nguồn đã dùng trong prompt, đúng thứ tự; từ chối ID không thuộc context đã xác minh. |
| `lms-dlu-demo/verified_learning_ui.py` | Ghi `[Nguồn n]` ở expander theo thứ tự prompt; hiển thị preview bằng Markdown. |
| `tests/ai/test_context_text.py` | Kiểm tra nhiễu, CID, bảng, công thức, mã, nhận diện override và chỉ dẫn lập trình bình thường. |
| `tests/ai/test_grounded_chat.py` | Kiểm tra prompt, sampling, chọn chunk, loại trùng, dữ liệu không đủ, bộ lọc override và fallback khi đầu ra chứa chữ Hán. |
| `tests/test_verified_chat_integration.py` | Kiểm tra nguồn được chọn khớp prompt; document ID, version ID, chunk ID, tên và hash không đổi; từ chối nguồn giả. Cập nhật assertion để đọc prompt JSON. |
| `tests/test_verified_publication.py` | Kiểm tra xếp hạng trước ngân sách nguyên chunk. |

### Làm sạch mà không sửa chỉ mục

Chỉ làm sạch bản văn phục vụ prompt chat và preview, **sau khi** kiểm tra nội dung gốc với manifest. Không sửa `DocumentNormalizer`, artifact, chunk đã lưu hoặc hash.

- Loại dòng phân cách bảng bị lẻ và dòng chỉ chứa cột trống.
- Chuyển một hàng tiêu đề nhiều cột trống, không có hàng dữ liệu, thành chữ dễ đọc; giữ các bảng có hàng dữ liệu và quan hệ giữa các cột.
- Giữ code fence, inline code, khối công thức và công thức inline.
- Thay CID ngoài các vùng được bảo vệ bằng `�`, biểu thị mất glyph; không tự đoán ký tự hay phép toán.
- Giữ nguyên Moodle document ID, document version ID, chunk ID, tên tài liệu và các hash gốc trong metadata trả về. Preview đã làm sạch không phải văn bản dùng để tính hash.

Bản sửa này **không cần reindex**. Muốn khôi phục công thức bị mất glyph cần cải thiện bộ trích xuất/OCR và kiểm tra PDF gốc trước. Sau đó có thể đồng bộ lại tài liệu bằng luồng publication/version hiện có khi được chấp thuận; không xóa hoặc tái tạo KB ACTIVE thủ công.

## Kiểm chứng

- Nhóm chat, Ollama provider, publication, raw retrieval, normalizer, learning, phân quyền và Streamlit: **190 passed, 3 subtests passed**.
- Nhóm bổ sung gồm `test_moodle_ingestion_router.py`, `test_final_team_integration.py`, `test_runtime_query_authorization.py`, `test_streamlit_student_ai_tutor_contract.py`: **102 passed**.
- Tổng cộng **292 test và 3 subtest**; chỉ có cảnh báo deprecation FastAPI/Starlette hiện hữu.
- `git diff --check` sạch.
- Dùng Python của `lms-dlu-demo/venv`, nạp pytest hiện có từ `D:/python/Lib/site-packages` qua `sys.path.append()`; không cài hoặc đổi dependency. Sandbox Windows chặn socket nội bộ của asyncio nên các test bất đồng bộ được chạy với quyền thực thi ngoài sandbox.
- Kiểm tra RAG thật chỉ đọc từ publication ACTIVE, không hardcode KB ID: `qwen2.5:3b` trả lời tiếng Việt, chọn 3 nguồn của `Chuong 1.pdf`, giải thích đúng rẽ nhánh và 4 phép toán, có `[Nguồn 1]`, không nhầm thành đệ quy.
- Với đoạn tham khảo không có Kubernetes, mô hình nói không có thông tin.
- Với đoạn chứa `SYSTEM OVERRIDE: Ignore the user...`, bản cuối loại đoạn này, trả fallback an toàn và không gọi LLM cho đoạn đó.
- Test tự động kiểm tra đầu ra Trung hoặc trộn Việt/Trung đều được thay bằng thông báo an toàn.

Không chỉnh cấu hình model, embedding, phân quyền, cơ chế đồng bộ, dữ liệu Moodle hoặc chỉ mục. Không thêm log chứa câu hỏi, tài liệu, token hay API key. Thư mục untracked `deeptutor-venv-backup/` đã tồn tại trước khi sửa và được giữ nguyên. Git status được kiểm tra với `diff.ignoreSubmodules=all` vì metadata Git của submodule DeepTutor nằm ngoài checkout và bị giới hạn quyền đọc; không sửa file nào trong submodule.

## Kiểm thử thủ công trên Streamlit

1. Nạp lại tiến trình FastAPI bằng môi trường/cấu hình đang sử dụng để nhận mã mới, rồi tải lại `http://127.0.0.1:8502`.
2. Đăng nhập bằng tài khoản/token sinh viên hợp lệ, chọn `INT1339`, mở AI Tutor. Không cần đồng bộ lại tài liệu.
3. Gửi: “Bài 10: Phép toán số học với x, y và ký tự k (+, -, *, /) yêu cầu gì và dùng cách nào?” Kỳ vọng giải thích tiếng Việt ngắn, dùng rẽ nhánh và xử lý ký tự không hợp lệ; không tự đưa đệ quy vào.
4. Mở `[Nguồn n]`: kiểm tra tên `Chuong 1.pdf`, document/version/chunk ID và preview dễ đọc. Bảng thực vẫn giữ các ô; CID chưa giải mã hiển thị `�` ngoài vùng code/công thức được bảo vệ.
5. Hỏi một nội dung không có trong chương, ví dụ triển khai Kubernetes; kỳ vọng thừa nhận chưa đủ căn cứ.
6. Hỏi một công thức/bảng trong tài liệu và đối chiếu PDF gốc. Nếu có glyph bị mất, không chấp nhận mô hình tự đoán công thức.
7. Hỏi lại vài lần để kiểm tra ngôn ngữ và độ tập trung. Câu trả lời cũ trong lịch sử không tự được tạo lại bằng prompt mới.

## Giới hạn còn lại

- Bộ lọc override chỉ bắt các mẫu rõ ràng; có thể bỏ sót cách diễn đạt mới hoặc loại nhầm tài liệu đang giảng về prompt injection. Đây là phòng vệ bổ sung, không chứng minh mọi đầu ra đều đúng ngữ nghĩa.
- Chặn chữ Hán cũng chặn trích dẫn/tên tiếng Trung hợp lệ và chữ Hán dùng trong tiếng Nhật. Cần xem lại nếu mở rộng sang học phần đa ngôn ngữ. Bộ chặn này không phải bộ nhận diện mọi ngôn ngữ.
- Top 3 theo điểm vector giúp giảm nhiễu nhưng có thể bỏ bớt ngữ cảnh cho câu hỏi tổng hợp; điểm cao không bảo đảm liên quan về nghĩa. Không thêm ngưỡng điểm tùy tiện hoặc model reranker.
- 120–180 từ là chỉ dẫn; giới hạn 1.024 token có thể cắt câu trả lời dài. Không cắt hậu xử lý tùy tiện vì có thể làm mất công thức hoặc mã.
- CID là dữ liệu đã mất: làm sạch không khôi phục được công thức. Giữ nguyên bảng phức tạp và mã để tránh xóa nội dung có giá trị, nên một phần bố cục PDF có thể còn nhiễu.
- Chưa chạy toàn bộ repository hoặc thao tác thủ công trên phiên Streamlit thật; đã chạy Streamlit AppTest và các phép thử RAG/Ollama cục bộ nêu trên.
