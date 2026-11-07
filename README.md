# Bãi đỗ xe IoT — nền tảng ESP32 và MQTT

Đây là mốc nền được tách từ bài hoàn thiện có sẵn của nhóm, không phải lịch sử phát triển gốc.
Phần bàn giao: firmware ESP32, cảm biến P1/P2 và cổng vào/ra, servo tự động/thủ công,
giao thức telemetry/ACK, parser MQTT và kiểm thử logic. Backend quản lý và giao diện được bổ sung ở các mốc tiếp theo.

## Kiểm tra base (từ thư mục gốc repo)

```powershell
python -m venv backend/.venv
./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
./backend/.venv/Scripts/python.exe -m pytest -q
New-Item -ItemType Directory -Force output | Out-Null
g++ -std=c++11 -Wall -Wextra -pedantic firmware/tests/gate_controller_test.cpp -o output/gate_controller_test.exe
./output/gate_controller_test.exe
```

Chạy tương tự cho `gate_sensor_test`, `mqtt_write_test`, `telemetry_delivery_test` trong `firmware/tests`.
Các bài C++ kiểm tra logic trên máy tính, chưa thay cho việc nạp ESP32 và đo trên mạch thật.

## Ranh giới bản này

Chưa có FastAPI, database hoặc dashboard. `mqtt/monitor.py` là công cụ subscribe dùng lại sau
khi mốc backend tạo broker/cấu hình local; không tự tạo tài khoản hoặc ACK thay backend.
Firmware hiện tại cần backend để xử lý ACK và lệnh từ xa khi chạy tích hợp.
Đọc `hardware/README.md` để đấu nối. Không dùng `config.example.h` làm mật khẩu chạy thật.

## Bước tiếp theo

Bổ sung FastAPI và SQLite để lưu telemetry, cung cấp API quản lý thiết bị,
đăng nhập và phân quyền. Sau đó tích hợp dashboard để theo dõi ô đỗ và điều khiển cổng.
