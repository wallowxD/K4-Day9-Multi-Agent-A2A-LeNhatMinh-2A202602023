# Hướng dẫn chạy hệ thống

Hệ thống dùng `llama3.2:3b` qua Ollama và orchestration multi-agent viết bằng Python chuẩn, không cần cài package Python bên ngoài.

## Chuẩn bị model

```bash
ollama pull llama3.2:3b
ollama serve
```

Model 3B đáp ứng giới hạn tối đa 10B parameters trong đề. Tên model được khai báo cố định tại `olist_agents/config.py` và được ghi lại vào `logging/metadata.json` sau mỗi lần chạy.

## Chạy chính thức

Nếu checkpoint không cung cấp sẵn JSON trong `input/`, tạo 50 case cân bằng và có thể tái lập trực tiếp từ Olist CSV:

```bash
python generate_inputs.py
```

Sau đó chạy:

```bash
python run.py --llm-mode required --zip-output output.zip
```

`required` bảo đảm lượt chạy nộp bài chỉ thành công khi Llama 3.2 thực sự phản hồi. Kết quả gồm:

- `output/EC_001.json` đến `output/EC_050.json`;
- `logging/trace.jsonl`, được ghi mới hoàn toàn ở mỗi lượt chạy;
- `logging/metadata.json`, phản ánh model và số model call thực tế;
- `output.zip`, chỉ chứa các JSON output.

Chế độ `auto` cho phép pipeline nghiệp vụ chạy khi đang phát triển mà Ollama chưa bật; trạng thái fallback được ghi rõ trong trace và metadata. Không dùng `auto` cho lượt chạy nộp bài.

## Kiểm thử

```bash
python -m unittest discover -v
python -m compileall -q olist_agents tests run.py
```

Để thử một tập input chưa đủ 50 case:

```bash
python run.py --allow-partial --llm-mode off
```

`--llm-mode off` chỉ dành cho kiểm thử deterministic; output chính thức phải dùng `required`.

## Nguyên tắc correctness

- CSV là nguồn sự thật cho ID, timestamp và amount; model không được sửa các trường này.
- `Decimal` và `ROUND_HALF_UP` được dùng cho tiền; giờ và tiền đều làm tròn hai chữ số.
- Policy được áp dụng đúng thứ tự ưu tiên trong `EC_POLICY_V2`.
- Verifier kiểm tra schema, giới hạn array, evidence tồn tại, null handling và quan hệ giữa refund/case status trước khi file được ghi.
- Nếu case không khớp bất kỳ primary issue nào trong policy, pipeline dừng thay vì tự tạo taxonomy mới.
