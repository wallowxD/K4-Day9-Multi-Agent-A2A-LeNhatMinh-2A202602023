# Báo cáo cá nhân — Day 9: Multi-Agent A2A

## 1. Thông tin cá nhân

| Thông tin | Nội dung |
| --- | --- |
| Họ và tên | Lê Nhật Minh |
| MSSV | 2A202602023 |
| Khóa/Lớp | K4 |
| Vai trò chính | Thiết kế và tích hợp hệ thống multi-agent |
| Ngày hoàn thành | 2026-08-05 |

Hai trường nhận dạng được để trống có chủ đích vì repo không cung cấp thông tin này; không tự bịa dữ liệu cá nhân.

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao | Trạng thái |
| --- | --- | --- | --- | --- |
| Orchestration và A2A handoff | `olist_agents/orchestrator.py` | Case JSON, specialist findings | Output nháp và trace | Hoàn thành |
| Policy và specialist agents | `olist_agents/agents.py` | CSV-backed handoffs | Phân tích customer/order/payment/delivery/policy | Hoàn thành |
| Data access và hard gate | `repository.py`, `verifier.py` | Olist CSV, output nháp | Indexed data, pass/error | Hoàn thành |
| Llama 3.2 runtime | `llm.py` | Handoff rút gọn | Model review có audit | Hoàn thành; lượt auto ghi nhận Ollama chưa khả dụng |
| Batch artifacts | `cli.py`, `trace.py`, `input_generator.py` | Olist CSV | 50 input, 50 output, trace, metadata, zip | Hoàn thành |

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Viết kiểm thử policy và rounding | Toàn pipeline | 13 test bao phủ sáu primary issue, action order, null timestamp, tiền, CLI và end-to-end |
| Tài liệu hóa | Người chạy/nộp bài | `architecture.md` và `IMPLEMENTATION.md` |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | Artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Cài đặt graph agent | `olist_agents/` | Coordinator + 6 specialist/verifier role | `python -m unittest discover -v` |
| Áp EC_POLICY_V2 | `agents.py` | Thứ tự primary, secondary, refund, action | `tests/test_policy.py` |
| Đối soát dữ liệu thật | `tests/test_integration.py` | Một order Olist đi qua toàn pipeline và verifier | Chạy unittest |
| Chuẩn bị batch runner | `run.py` | Kiểm tra đúng 50 input, output atomic, zip sạch | `python run.py --help` |
| Sinh và chạy dữ liệu | `generate_inputs.py`, `input/`, `output/` | Olist CSV | 50 case và 50 kết quả | Kiểm tra số file, trace và ZIP |

Artifact cụ thể là output end-to-end cho order `e481f51cbdc54678b7cc49136f2d6af7` được test trong thư mục tạm. Case được phân loại `valid_split_payment`, các payment row reconciled và refund bằng 0; trace chứa sự kiện `hard_gate_passed`.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Một claim phải được đối chiếu qua customer, order/item/product, payment và delivery trước khi áp policy. Các nguồn có quan hệ one-to-many nên nếu join phẳng sẽ dễ nhân đôi tiền. Model ngôn ngữ cũng không phù hợp để tự tính số tiền hoặc tạo evidence ID.

### Cách triển khai

Repository index từng bảng theo khóa, giữ thứ tự CSV. Coordinator cho Customer và Order Agent chạy song song; sau item handoff, Payment và Delivery Agent chạy song song. Policy Agent chỉ nhận structured findings. Mỗi agent gửi payload rút gọn cho `llama3.2:3b` review, nhưng các trường định lượng do Python/Decimal quyết định. Verifier đọc lại nguồn để chặn evidence giả, ID sai, array quá giới hạn, null sai hoặc status/refund mâu thuẫn.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | `EC_NNN.json`, `policy_version=EC_POLICY_V2`, claimed order tồn tại |
| Output | JSON đúng schema mục 6 của README |
| Module phụ thuộc | `repository`, specialist agents, policy, verifier, Llama runtime |
| Module sử dụng output | Batch writer và zip packager |
| Điều kiện lỗi | Thiếu input/CSV, order không tồn tại, policy không match, Ollama thiếu trong required mode, hard gate fail |

### Cách xác minh

```bash
python -m unittest discover -v
python -m compileall -q olist_agents tests run.py
python run.py --help
```

- **Kết quả mong đợi:** test pass, source compile được, CLI hiển thị tham số.
- **Kết quả thực tế:** 13/13 test pass sau khi hoàn tất triển khai; compile thành công.
- **Artifact/log:** `output/` có đủ 50 JSON; `logging/trace.jsonl` có 750 dòng hợp lệ; `output.zip` có đúng 50 entry JSON.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Đề yêu cầu dùng multi-agent/model nhưng output có amount, timestamp và evidence cần chính xác tuyệt đối.
- **Các phương án đã cân nhắc:** Cho LLM tự đọc CSV và sinh toàn bộ JSON; hoặc dùng agent orchestration với deterministic tools và LLM review từng handoff.
- **Phương án đã chọn:** Structured multi-agent handoff, deterministic computation là authoritative, Llama 3.2 làm bounded semantic reviewer.
- **Lý do:** Giảm hallucination, tránh duplicate payment do join, tái lập được và vẫn có model call thật/audit rõ ở từng agent.
- **Bằng chứng:** Unit test kiểm tra thứ tự policy; integration test đối chiếu một order thật và vượt verifier.

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng:** Ban đầu `input/` và `output/` chỉ có `.gitkeep`; Ollama executable không có trên máy.
- **Bước tái hiện:** Liệt kê thư mục input/output và kiểm tra `Get-Command ollama`.
- **Nguyên nhân gốc:** Checkpoint input chưa được đưa vào repo và local runtime/model chưa cài.
- **Cách xử lý:** Thêm bộ chọn deterministic lấy order trực tiếp từ Olist CSV, cân bằng đủ sáu nhánh policy; chạy 50 case bằng chế độ `auto` và ghi trung thực trạng thái model unavailable.
- **Cách xác minh sau khi sửa:** Có 50 input, 50 output, 750 trace row hợp lệ, ZIP có 50 JSON và 13/13 test pass.
- **Điều học được:** Audit artifact chỉ có ý nghĩa khi phản ánh lượt chạy thật; nên dừng minh bạch thay vì làm đầy deliverable bằng dữ liệu giả.

Phạm vi còn lại là model call thật: metadata hiện ghi 350 call thất bại vì Ollama chưa cài xong. Cần cài/pull `llama3.2:3b`, rồi chạy lại lệnh `required` trong `IMPLEMENTATION.md` để thay trace fallback.

## 7. Hiểu biết về luồng end-to-end

1. Coordinator nhận claimed order, Customer Agent tìm `customer_unique_id` và lịch sử; Order Agent lấy item/seller/product/category; Payment và Delivery Agent tính trên handoff; Policy Agent kết luận; Verifier đối chiếu lại trước khi ghi.
2. Payment không join phẳng với item vì sẽ nhân bản row. Hai tổng được tính độc lập rồi so `payment_total - (item + freight)` với tolerance 0.10 BRL.
3. Seller chịu trách nhiệm khi carrier handoff sau shipping limit sớm nhất của ít nhất một seller và giao cuối cùng trễ estimate; nếu giao trễ nhưng không seller nào handoff trễ thì logistics chịu trách nhiệm.
4. Evidence chỉ gồm ID dựng trực tiếp từ order/item/payment/seller tồn tại và root-cause policy đã chọn. Verifier loại mọi ID ngoài whitelist và dữ liệu nguồn.
5. Llama 3.2 hỗ trợ review ngữ nghĩa nhưng không ghi đè số liệu. Trace phân biệt rõ model call completed, unavailable hay disabled để không đánh đồng fallback với lượt chạy model thật.

## 8. Cam kết của thành viên

- [x] Nội dung kỹ thuật phản ánh đúng phần triển khai trong repo.
- [x] Có thể giải thích luồng end-to-end và contract giữa các agent.
- [x] Không ghi đã chạy 50 case hoặc Llama thành công khi input/runtime chưa có.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Họ tên và MSSV cần được chủ repo bổ sung trước khi nộp.

**Họ và tên:** Lê Nhật Minh

**Ngày xác nhận:** 2026-08-05
