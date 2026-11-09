# Chạy bằng PyCharm trên máy đã thiết lập

1. Nếu PyCharm đã mở từ trước lúc thiết lập, đóng/mở lại ứng dụng để nạp interpreter mới.
2. File → Open thư mục gốc repo vừa clone, nơi có `backend`, `frontend`, `mqtt` và `esp32_core`.
3. Chọn cấu hình **IoT Dashboard** trong danh sách Run, bấm **Run ▶** hoặc **Debug**.
4. Mở **http://127.0.0.1:8000/**; tài khoản ở `mqtt/runtime/THONG_TIN_DANG_NHAP.txt`.

Cấu hình lưu ở `.run/IoT_Dashboard.run.xml`, chạy `backend/run_pycharm.py` bằng virtualenv
`backend/.venv/Scripts/python.exe` qua interpreter của module IOT. Launcher tự bật broker Mosquitto nếu chưa chạy, giữ nguyên
mật khẩu/config đã có, đọc `mqtt/runtime/backend.env`, rồi chạy FastAPI và dashboard cùng tiến trình
Run/Debug. Không mở thêm cửa sổ hoặc trình duyệt; không cần Node.js.
Khi bật broker, nếu IP cũ không còn trên máy, launcher tự cập nhật địa chỉ LAN trong cấu hình broker,
`connection.json`, `config.local.h` và file thông tin đăng nhập, giữ nguyên mật khẩu và quyền MQTT.
Backend quảng bá tên `parkflow-iot.local` bằng mDNS và cập nhật khi IPv4 LAN đổi. Firmware 0.2.1 trở lên
tra lại tên này mỗi lần kết nối MQTT; IP trong `config.local.h` chỉ là dự phòng.
Nạp firmware mới một lần và chạy lại `mqtt/Enable-Firewall.cmd` một lần để cập nhật quy tắc MQTT/mDNS.
Sau đó đổi IP trong cùng LAN không cần nạp lại ESP32; backend cần chạy và mạng phải cho phép mDNS.

Đăng ký interpreter `Python 3.13 (IOT)` trong PyCharm là thiết lập riêng trên máy hiện tại.
Nếu chuyển repo sang máy khác, cần Setup và chọn lại virtualenv trên máy đó.

## Dừng và chạy lại

- Nút **Stop** trong PyCharm dừng backend; broker tiếp tục chạy nền để lần Run sau dùng lại.
- Để dừng broker do dự án quản lý, chạy từ Terminal tại thư mục IOT:

```powershell
powershell -ExecutionPolicy Bypass -File .\mqtt\Stop-IOT.ps1
```

- Thay đổi Python: Stop rồi Run lại. Thay đổi HTML/CSS/JS: tải lại trang trình duyệt.
- Không chạy đồng thời `Start-IOT.ps1` đầy đủ và cấu hình PyCharm trên cổng 8000.
  Nếu đã dùng bản chạy nền, chạy Stop-IOT trước khi bấm Run trong PyCharm.
- `Start-IOT.ps1 -BrokerOnly` chỉ bật/tái sử dụng broker, dành cho launcher PyCharm.

## Xử lý lỗi

| Thông báo | Cách xử lý |
|---|---|
| Port 8000 is unavailable | Dừng phiên Run cũ hoặc dùng Stop-IOT nếu đó là backend chạy nền của dự án. Không dừng tiến trình lạ. |
| Missing dependencies | Chọn lại interpreter `backend/.venv/Scripts/python.exe`. |
| Nút Run quay nhưng chưa có console; log báo SDK is not defined | IDE chưa gắn đúng interpreter. Run dùng interpreter của module IOT; Project Interpreter phải là `Python 3.13 (IOT)` với đường dẫn virtualenv ở trên. Tắt IDE trước khi sửa file cấu hình/cache SDK bên ngoài để tránh bị ghi đè. |
| Local configuration is missing | Chạy `mqtt/Setup.ps1` từ thư mục gốc repo. |
| The requested address is not valid in its context | Broker đang dùng IP cũ. Launcher sẽ tự cập nhật khi broker khởi động lại; máy cần kết nối Wi-Fi/LAN. Xem IP mới trong `mqtt/runtime/connection.json`. |
| Dashboard hiện chưa xác định | Xem `/health`, kiểm tra ESP32 có `Wi-Fi OK` và `MQTT OK`; kiểm tra broker, Wi-Fi và LAN. |

ESP32 tự dùng Wi-Fi đã lưu khi cấp nguồn. Khi chuyển sang Wi-Fi khác, dùng cổng cấu hình để đổi Wi-Fi
trên ESP32; máy tính và ESP32 cần truy cập cùng LAN. Xem hướng dẫn `mqtt/README.md`.
