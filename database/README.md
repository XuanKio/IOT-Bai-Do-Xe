# Database

SQLite local: `backend/parking.db`, không commit dữ liệu thật.
Schema được khai báo bằng SQLAlchemy trong `backend/app/main.py` và `backend/app/domain.py`.
`schema.sql` là bản DDL cho database mới, không phải script xóa/tạo lại database đang dùng.

- users, devices, slots, alerts, audit_logs: tài khoản, thiết bị, trạng thái mới nhất, cảnh báo và thao tác quản trị.
- sensor_telemetry, sensor_slot_readings: mẫu thay đổi hoặc checkpoint 60 giây và giá trị từng ô; giữ 3 ngày.
- live_telemetry: một trạng thái mới nhất mỗi thiết bị, không phụ thuộc lịch sử đã hết hạn.
- hourly_occupancy: tổng số giây có xe, trống và chưa xác định theo giờ; giữ 365 ngày.
- storage_state: mốc chạy tổng hợp và dọn dữ liệu theo lô.
- device_details, device_grants, device_slots: cấu hình/thông tin thiết bị, quyền truy cập, gán ô.
- seen_packets, device_boots: phát hiện trùng, bản tin sai thứ tự và boot cũ.
- parking_events: sự kiện thay đổi trạng thái ô, bao gồm khoảng mất dữ liệu.
- alert_details: điều kiện cảnh báo đang diễn ra, thời điểm phục hồi và người xác nhận.
- device_commands: yêu cầu điều khiển/cấu hình, retry, timeout, ACK và kết quả.

Nâng cấp v0.1 → v0.2 chỉ bổ sung bảng, không xóa hoặc đổi các cột telemetry cũ. Startup gọi
`metadata.create_all` để bổ sung các bảng thiếu. Trước khi nâng cấp, đã tạo bản sao bằng SQLite backup API
trong `mqtt/runtime/backups/` (không commit). Các thay đổi cột ở phiên bản sau cần migration riêng;
create_all không thay thế migration thay đổi schema.

Timestamp lưu UTC. Chính sách tự dọn mẫu/sự kiện/tổng hợp được mô tả trong [STORAGE.md](../docs/STORAGE.md).
Không lưu mật khẩu người dùng dạng rõ trong database; mật khẩu thiết bị
được broker lưu băm. File cấu hình local chứa thông tin kết nối cần thiết nhưng nằm ngoài Git.
