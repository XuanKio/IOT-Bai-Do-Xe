# Backend bãi đỗ xe IoT

Backend kế thừa nền tảng ESP32/MQTT và cung cấp FastAPI, SQLite/SQLAlchemy,
đăng nhập JWT và phân quyền admin/operator/viewer, quản lý thiết bị, MQTT receiver có ACK,
lịch sử, cảnh báo bãi đầy, lệnh điều khiển, CSV và kiểm thử API.
Mã được tách từ bài hoàn thiện có sẵn của nhóm; các mốc này phục vụ bàn giao và review.

## Chạy API không cần phần cứng (từ gốc repo)

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
./backend/.venv/Scripts/python.exe -m pytest -q
Push-Location backend
./.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Dừng bằng Ctrl+C rồi `Pop-Location`. Mở http://127.0.0.1:8000/docs để thử API.
Đường dẫn `/` chuyển đến Swagger ở mốc này. Chưa có dashboard ParkFlow.
Tạo tài khoản admin bằng `python -m app.create_admin` trong thư mục backend với Python của venv;
chương trình hỏi thông tin, không có mật khẩu mặc định. Đặt JWT_SECRET ổn định khi chạy lâu dài.

## Chạy với MQTT/ESP32

```powershell
./mqtt/Setup.ps1
./mqtt/Start-IOT.ps1
```

Script tạo cấu hình/mật khẩu local, cài broker và khởi động API. Tham khảo `mqtt/README.md`,
`docs/BACKEND.md`, `database/README.md` và `hardware/README.md`; các chỗ nhắc dashboard trong
tài liệu kiến trúc là phần sẽ được bổ sung tại mốc giao diện. Thiết lập thực tế cần LAN và phần cứng phù hợp.
Không commit `.env`, `mqtt/runtime`, `config.local.h`, database, log hoặc `.tools`.

## Bước tiếp theo

Bổ sung dashboard ParkFlow, kiểm thử giao diện và kết nối giao diện với API.
