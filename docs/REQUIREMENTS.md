# Đối chiếu yêu cầu đồ án IoT

Đối chiếu theo đề bài học phần do nhóm cung cấp, các mục 4.2–4.6, 6–8. Phạm vi là backend và dashboard
cho một bãi xe hai ô; người dùng yêu cầu tạm bỏ servo SG90.

| Nhóm tiêu chí | Phần triển khai | Phần còn lại |
|---|---|---|
| Người dùng | API và giao diện tạo tài khoản, đăng nhập/đăng xuất, đổi mật khẩu, khóa tài khoản, ba vai trò | Chuẩn bị tài khoản demo theo nhóm |
| Phạm vi quyền | DeviceGrant, kiểm tra backend và giao diện theo quyền thiết bị/telemetry/cảnh báo/lệnh/CSV | Ghi hình demo theo vai trò |
| Vòng đời thiết bị | Giao diện onboarding, mật khẩu MQTT riêng, gán user/vị trí/ô, active/maintenance/revoked/decommissioned | Bằng chứng demo với broker thật |
| Kết nối thật | Hai LM393 ở D27/D26, Wi-Fi/MQTT, reconnect, heartbeat qua telemetry và LWT | Đo độ ổn định dài hạn |
| Dữ liệu | Timestamp UTC, boot/seq, kiểm tra hợp lệ, lịch sử, bộ lọc UTC+7, biểu đồ thời gian quan sát, chính sách lưu/dọn dữ liệu và CSV trên web | Đo, thu số liệu thực nghiệm |
| Giám sát | Trang viewer riêng để tìm chỗ đỗ, dashboard kỹ thuật responsive, unknown khi không có dữ liệu mới | Kiểm tra trên điện thoại thật nếu triển khai truy cập LAN |
| Cảnh báo | Giao diện offline/bãi đầy, timeout lệnh, lịch sử, quy tắc và xác nhận tách biệt khỏi hết điều kiện | Demo ngắt mạng/bãi đầy với phần cứng thật |
| Cấu hình/ACK | Ping, đổi chu kỳ gửi, retry/timeout, lịch sử lệnh, xác nhận từ ESP32 | Điều khiển servo được tạm hoãn |
| Bảo mật | Hash mật khẩu, JWT trong sessionStorage, scope, MQTT ACL riêng, thu hồi trên broker, giao diện audit, CSP, secret ngoài Git | TLS/HTTPS và kiểm tra khi triển khai Internet |
| Sản phẩm nộp | Source frontend/backend, schema, tài liệu API/topic/giao diện, test tự động, script chạy local | Hoàn thiện ERD/sơ đồ, báo cáo/slide cập nhật và bằng chứng demo theo nhóm |

Kiểm thử giao diện bằng server mô phỏng tách biệt không thay thế phép đo với ESP32 thật hoặc chứng minh
toàn bộ đồ án đã hoàn thành. Chưa triển khai OTA, AI, nhận diện biển số,
tính phí hay cổng tự động. Hai cảm biến cùng một loại không được mô tả là hai loại cảm biến khác nhau.
