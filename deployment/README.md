# Triển khai local

Các script Windows và cấu hình sinh tự động nằm trong [`mqtt/`](../mqtt/README.md).
Mosquitto 2.1.2 portable được tải từ trang chính thức và bật plugin Dynamic Security.
Backend dùng tài khoản dịch vụ receiver; broker_admin chỉ được backend sử dụng để quản trị quyền MQTT.
Thiết bị dùng username/password riêng, ACL chỉ cho phép gửi telemetry/ACK/status của chính nó và nhận command của chính nó.

Chạy Setup để sinh secret/config, Start-IOT để chạy nền, Monitor để xem, Stop-IOT để dừng.
Dashboard ParkFlow được backend phục vụ tại **http://127.0.0.1:8000/**; Swagger ở `/docs`.
Frontend dùng HTML/CSS/ES modules cùng origin, không cần Node.js, bước build hoặc mở thêm cổng.
Không cần cài service hệ thống. Firewall chỉ mở cổng MQTT cho executable của dự án từ LocalSubnet.
Nếu đổi IP máy tính trong cùng LAN: khởi động lại bằng Start-IOT hoặc launcher PyCharm để cập nhật địa chỉ broker; backend quảng bá `parkflow-iot.local` và firmware tự tìm lại qua mDNS. Không cần tạo lại mật khẩu hoặc nạp lại nếu mDNS hoạt động; xem `mqtt/README.md` khi mạng chặn mDNS hoặc đổi Wi-Fi của ESP32.
Môi trường này chưa dùng Docker, TLS hoặc cloud; không mở cổng trực tiếp ra Internet.
