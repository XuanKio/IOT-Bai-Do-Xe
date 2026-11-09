# Bãi đỗ xe IoT — ESP32, MQTT và FastAPI

Nguyên mẫu một bãi xe với hai ô đỗ: **P1 dùng D27, P2 dùng D26**; cảm biến **cổng vào dùng D32, cổng ra dùng D33**. Bốn cảm biến LM393 gửi trạng thái
qua Wi-Fi/MQTT; backend lưu lịch sử, quản lý tài khoản/thiết bị, phân quyền và sinh cảnh báo.
Dashboard web **ParkFlow** chạy cùng backend, hỗ trợ máy tính và điện thoại. Hai servo cổng vào/ra có chế độ tự động theo cảm biến và điều khiển thủ công dành cho admin.

```text
LM393 P1/P2 → ESP32 ↔ Mosquitto ↔ FastAPI → SQLite
                                  ↓
                       ParkFlow / Monitor / Swagger API
```

## Chạy trên Windows

Cần Python, Arduino IDE có ESP32 core, Wi-Fi 2.4 GHz cho ESP32; máy tính và ESP32 truy cập được cùng LAN.

```powershell
python -m venv backend\.venv
.\mqtt\Setup.ps1
.\mqtt\Start-IOT.ps1
```

Nếu PowerShell chặn script, dùng `powershell -ExecutionPolicy Bypass -File .\mqtt\Setup.ps1`.
Broker mặc định dùng cổng **1884**, tránh dịch vụ đang dùng 1883 trên máy phát triển.
Chạy `mqtt/Enable-Firewall.cmd` một lần với quyền Administrator để cho phép MQTT từ mạng LAN.

Mở dashboard **http://127.0.0.1:8000/**; Swagger API ở **http://127.0.0.1:8000/docs**.
Không cần Node.js hoặc chạy thêm frontend server. Tài khoản quản trị được tạo với mật khẩu ngẫu nhiên ở
`mqtt/runtime/THONG_TIN_DANG_NHAP.txt`. Không có mật khẩu thật nào được lưu trong repo.

## Nạp ESP32

```powershell
.\mqtt\Upload-ESP32.ps1 -Port COM5
```

Thay COM5 bằng cổng thực tế. Mã nguồn chính nằm ở **`esp32_core/esp32_core.ino`**.
Setup tạo `config.local.h` với địa chỉ và tài khoản MQTT. Lần đầu, kết nối Wi-Fi `ESP32-IOT-Setup`
bằng điện thoại, dùng mật khẩu cấu hình trong file thông tin ở trên và mở **http://192.168.4.1**.
Nhập Wi-Fi 2.4 GHz cùng mạng với máy tính. Mở `mqtt/Monitor.cmd` để xem trạng thái hai ô.

## Chức năng backend

- Tạo tài khoản, đăng nhập/đăng xuất, đổi mật khẩu, khóa tài khoản; vai trò admin/operator/viewer.
- Cấp quyền theo từng thiết bị; người không được cấp quyền không xem được dữ liệu của thiết bị đó.
- Onboarding với mật khẩu MQTT riêng; quản lý vị trí, firmware/hardware, bảo trì và vòng đời thiết bị.
- Thu hồi/decommission được áp dụng lên broker bằng Mosquitto Dynamic Security.
- Telemetry theo thời gian, phát hiện bản tin trùng bằng boot ID/sequence, lịch sử từng ô và sự kiện đổi trạng thái.
- Cảnh báo bãi đầy và mất kết nối (bật riêng theo thiết bị, mặc định tắt); tự kết thúc và giữ lịch sử. Có thể ghi nhận người đã xem cảnh báo.
- Nhật ký đăng nhập thành công/thất bại, đổi mật khẩu và xuất CSV; chỉ admin xem nhật ký.
- Lệnh `ping` và đổi chu kỳ gửi từ 500–10000 ms, có retry, timeout, idempotency key và ACK từ ESP32.
- Lọc theo thời gian, tổng hợp thời gian có xe/trống/chưa xác định theo giờ và xuất CSV lịch sử.
- Dữ liệu hiện tại cập nhật liên tục; lịch sử lưu khi đổi trạng thái hoặc mỗi 60 giây. Giữ mẫu 3 ngày, sự kiện 90 ngày, tổng hợp 365 ngày. Không suy diễn biển số, lượt xe hoặc phí gửi xe.

## Dashboard web

- Trang viewer riêng để tìm chỗ: số chỗ trống/tổng số chỗ, sơ đồ P1/P2 có lối vào/ra và chọn vị trí.
- Trang admin/operator có trạng thái có xe/trống/chưa xác định; mất dữ liệu mới không hiển thị thành chỗ trống.
- Lịch sử cảm biến/sự kiện, bộ lọc UTC+7, biểu đồ thời gian có xe theo giờ và xuất CSV có kiểm tra quyền.
- Đăng ký/cấp kết nối MQTT, thông tin thiết bị, vòng đời, gán ô và quyền theo từng người dùng.
- Tổng quan tối giản: số chỗ trống, sơ đồ ô đỗ và cảnh báo khi bãi đầy; biểu đồ/lịch sử nằm ở trang riêng.
- Ping, đổi chu kỳ gửi, theo dõi ACK/retry/timeout và cấu hình cảnh báo bãi đầy/mất kết nối.
- Quản lý tài khoản và nhật ký dành cho admin; đổi mật khẩu cá nhân.

Giao diện dùng API thật cùng origin, cập nhật mỗi 3 giây; không có số liệu mẫu trong bản chạy thật.
Xem [hướng dẫn frontend](frontend/README.md) để chạy và kiểm thử với dữ liệu mô phỏng tách biệt.

## Kiểm tra

```powershell
.\backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.\backend\.venv\Scripts\python.exe -m pytest -q
.\backend\.venv\Scripts\python.exe mqtt\check_setup.py
```

## Tài liệu

- [Backend và API](docs/BACKEND.md)
- [Dashboard frontend](frontend/README.md)
- [Chạy bằng PyCharm](docs/PYCHARM.md)
- [Chính sách lưu trữ và giao diện viewer](docs/STORAGE.md)
- [Đối chiếu yêu cầu đồ án](docs/REQUIREMENTS.md)
- [Đấu nối phần cứng](hardware/README.md)
- [Database](database/README.md)
- [MQTT và triển khai local](mqtt/README.md)

Mô hình hiện chạy trong LAN, MQTT TCP chưa có TLS, API chỉ lắng nghe localhost. Cần cấu hình HTTPS/TLS
và triển khai phù hợp trước khi đưa lên Internet. Khóa/mật khẩu, database, bản sao lưu, log và công cụ
đã tải về đều bị loại khỏi Git bằng `.gitignore`.

Thư viện sử dụng: [ESP32 Arduino](https://github.com/espressif/arduino-esp32),
[PubSubClient](https://github.com/knolleary/pubsubclient), [WiFiManager](https://github.com/tzapu/WiFiManager),
[ArduinoJson](https://arduinojson.org/), [Mosquitto](https://mosquitto.org/),
[Paho MQTT](https://eclipse.dev/paho/), [FastAPI](https://fastapi.tiangolo.com/),
[SQLAlchemy](https://www.sqlalchemy.org/). Code và tài liệu được hỗ trợ bằng AI; nhóm cần hiểu, kiểm thử
và giải thích được các phần sử dụng khi bảo vệ đồ án.
