# Chính sách dữ liệu và giao diện theo vai trò

Hệ thống tiếp tục dùng **SQLite**. Không chuyển PostgreSQL, không thay tài khoản hoặc mật khẩu.
Các bảng bổ sung được tạo bằng `create_all`; bảng lịch sử cũ giữ cấu trúc ban đầu.
Trước khi triển khai thay đổi đã có bản sao SQLite nhất quán trong `mqtt/runtime/backups/`.

## Dữ liệu hiện tại và lịch sử

ESP32 vẫn gửi mỗi giây theo cấu hình hiện có. Không cần nạp lại firmware cho thay đổi này.

- `live_telemetry`: một dòng cho mỗi thiết bị, cập nhật khi nhận bản tin hợp lệ. Lưu trạng thái mới nhất,
  thời điểm nhận, hạn hiệu lực và watermark tổng hợp. API hiện tại không phụ thuộc tuổi mẫu lịch sử.
- `sensor_telemetry` / `sensor_slot_readings`: thêm khi trạng thái đổi, khởi động mới, khôi phục sau
  gián đoạn hoặc đến mốc **60 giây**. Giữ **3 ngày**. Đây là mẫu thay đổi/định kỳ, không phải toàn bộ gói thô.
- `parking_events`: ghi thay đổi trạng thái và gián đoạn, giữ **90 ngày**.
- `hourly_occupancy`: tổng số giây có xe, trống và chưa xác định theo thiết bị/ô/giờ UTC, giữ **365 ngày**.
- Bản tin thiết bị thật dùng watermark boot/sequence trong `device_details` và một dòng `device_boots`
  cho mỗi lần khởi động; không thêm một dòng chống trùng cho mỗi bản tin. Lịch sử boot được giữ để
  chặn phát lại boot cũ. Các dòng `seen_packets` cũ/mô phỏng được giữ **1 ngày**.

Với trạng thái không đổi, 121 bản tin trong 120 giây chỉ thêm 3 mẫu lịch sử (mốc 0, 60, 120),
nhưng trạng thái hiện tại vẫn cập nhật đủ. Số mẫu tăng thêm khi có thay đổi thực tế.

Dọn dữ liệu theo lô tối đa 10.000 dòng mỗi bảng/lượt, kiểm tra mỗi **5 phút**. Xóa dòng trạng thái con
trước dòng telemetry cha. Dữ liệu hiện tại không bị xóa theo lịch sử; không tự chạy VACUUM.
SQLite có thể giữ nguyên dung lượng file sau khi dọn và tái sử dụng các trang trống cho dữ liệu mới.
Không dọn tài khoản, grant, mật khẩu hoặc audit log theo chính sách telemetry này.

## Thống kê thời gian

Khoảng giữa hai lần nhận được phân bổ theo trạng thái đã biết của mẫu trước. Sau hạn hiệu lực,
khi có LWT offline, hoặc khi chuyển bảo trì/thu hồi, thời gian được phân loại **chưa xác định**.
Không coi khoảng mất kết nối là thời gian trống. Watermark `accounted_until` ngăn tính lặp khi nhận
bản tin hoặc khi tiến trình tổng hợp chạy lại. Khoảng vượt ranh giới giờ được tách theo giờ UTC.

Tỷ lệ có xe = giây có xe / (giây có xe + giây trống). Thời gian chưa xác định được hiển thị riêng.
Đây là thời gian trạng thái theo quan sát cảm biến và hạn hiệu lực, không phải nhận diện từng xe.
Không suy diễn khoảng trước mẫu đầu tiên. Dữ liệu tổng hợp bắt đầu từ trạng thái được tiếp nhận bởi
cơ chế mới, có thể tiếp nối mẫu cũ gần nhất; không biến số lượng mẫu cũ thành thời gian đỗ.

Tổng hợp định kỳ **30 giây**, đồng thời chốt khoảng trước khi tiếp nhận mẫu mới. `/parking/utilization`
trả các bucket giờ giao với bộ lọc, làm tròn ra ranh giới giờ và trả `from_at`, `to_at`, `range_mode=whole_hours`.
Giao diện ghi rõ thống kê theo giờ; bộ lọc lịch sử/CSV vẫn chính xác theo mốc thời gian người dùng nhập.
Endpoint `/telemetry/statistics` cũ vẫn đếm mẫu **được giữ lại**, không dùng để tính tỷ lệ thời gian.

Triển khai local dùng một tiến trình backend; khóa trong tiến trình giữ nhất quán việc cập nhật
watermark và các tổng thời gian. Không chạy nhiều worker nhận MQTT đồng thời với cấu hình này.

## Viewer dành cho người tìm chỗ đỗ

Viewer chỉ truy cập `/parking/overview` và các API tài khoản cá nhân. API nhà xe kiểm tra grant,
chỉ trả mã ô, khu vực, trạng thái, thời điểm cập nhật và hạn hiệu lực, kèm số ô theo trạng thái.
Không trả GPIO, firmware, device ID, chu kỳ gửi hoặc lịch sử kỹ thuật.

Các API thiết bị, telemetry/CSV, lệnh, quy tắc, sự kiện và cảnh báo kỹ thuật dành cho admin/operator.
API người dùng, audit và chính sách lưu trữ dành cho admin. Chặn ở backend cả khi nhập đường dẫn trực tiếp.

Giao diện viewer có số xe/tổng sức chứa, số chỗ còn lại, sơ đồ mô phỏng P1/P2, lối vào/ra, trạng thái từng ô và
thông tin vị trí khi chọn ô. Không có đặt chỗ hay điều khiển cổng. Tài khoản chưa có grant không thấy
nhà xe của người khác. Mất API hoặc mẫu hết hạn thì ô thành **chưa xác định**, không hiển thị thành bãi đầy.

Viewer gọi một API nhà xe mỗi **3 giây**, kèm kiểm tra hồ sơ mỗi 30 giây; không tải các API kỹ thuật.
Console MQTT ghi khi trạng thái/boot đổi hoặc mỗi 60 giây. Launcher local tắt access log cho mỗi
yêu cầu HTTP để giảm log lặp; audit thao tác quản trị vẫn được giữ.
