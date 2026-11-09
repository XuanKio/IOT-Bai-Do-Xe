# ParkFlow — dashboard bãi đỗ xe hai ô

Giao diện tiếng Việt cho backend FastAPI sẵn có, P1/D27 và P2/D26. HTML/CSS/JavaScript ES modules
không dùng CDN, không cần npm, Node.js hoặc bước build khi chạy thật. FastAPI phục vụ `/` và `/assets/`;
mọi yêu cầu dữ liệu dùng API cùng origin. Dữ liệu trong bản chạy thật luôn lấy từ backend.
Viewer có trang tìm chỗ đỗ riêng; admin/operator dùng bảng điều khiển kỹ thuật.

## Chạy với ESP32

Từ thư mục gốc repo, sau khi đã chạy Setup và nạp firmware:

```powershell
.\mqtt\Start-IOT.ps1
```

Mở **http://127.0.0.1:8000/** và đăng nhập bằng tài khoản trong
`mqtt/runtime/THONG_TIN_DANG_NHAP.txt`. Không có mật khẩu mặc định trong mã frontend.
`/docs` vẫn là Swagger. Nếu backend đang chạy bản mã cũ, dừng/khởi động lại bằng
`mqtt/Stop-IOT.ps1` và `mqtt/Start-IOT.ps1` để nạp các thay đổi Python.
Không tự mở giao diện hoặc thêm firewall rule khi khởi động.

Backend mặc định chỉ lắng nghe localhost; bố cục đáp ứng màn hình nhỏ không đồng nghĩa điện thoại
khác trong LAN đã truy cập được. Cần cấu hình host, HTTPS và firewall phù hợp khi triển khai ngoài máy.

## Trang và quyền

| Trang | Chức năng | Quyền |
|---|---|---|
| Nhà xe (viewer) | Số xe/tổng sức chứa, chỗ còn lại, sơ đồ P1/P2, lối vào/ra, chọn vị trí, trạng thái mới nhất | Viewer theo grant; chỉ gọi `/parking/overview` |
| Tổng quan | Sơ đồ bãi xe với P1/P2, đường nội bộ, hai ô chờ và thanh chắn vào/ra; cảnh báo bãi đầy | Admin/operator theo thiết bị được cấp |
| Thiết bị | Tìm/lọc; xem vị trí, firmware/hardware, kết nối, lần nhận mới nhất | Admin/operator theo thiết bị được cấp |
| Chi tiết thiết bị | Đăng ký, provision, đổi thông tin, vòng đời, gán P1/P2, grant và đổi mật khẩu MQTT | Admin |
| Dữ liệu & lịch sử | Chọn thiết bị/khoảng thời gian, biểu đồ, mẫu/sự kiện, tải thêm, CSV | Admin/operator theo thiết bị được cấp |
| Cảnh báo | Bãi đầy/mất kết nối; lọc đang diễn ra/lịch sử, tự kết thúc; ghi nhận người đã xem | Admin/operator theo scope |
| Lệnh & cấu hình | Ping, chu kỳ 500–10.000 ms, timeout 5–60 giây, ACK/retry, bật/tắt cảnh báo bãi đầy/mất kết nối và ngưỡng dữ liệu | Admin; operator cần grant tương ứng |
| Người dùng | Tạo tài khoản, sửa vai trò, khóa/mở tài khoản | Admin |
| Nhật ký | 200 thao tác gần nhất | Admin |
| Tài khoản | Hồ sơ và đổi mật khẩu | Chủ tài khoản |

UI kỹ thuật dùng `/devices/{id}/permissions` để bật/tắt thao tác. Viewer bị chặn các API kỹ thuật ở backend, kể cả truy cập trực tiếp; vẫn được xem nhà xe và quản lý mật khẩu cá nhân.
Tài khoản không có grant nhìn thấy trạng thái chưa có thiết bị và không có số liệu của người khác.
Việc thu hồi, đổi vai trò hoặc khóa tài khoản được backend áp dụng cả với các phiên đã đăng nhập.

## Cách đọc dữ liệu

- Poll API mỗi **3 giây**; viewer chỉ tải một API nhà xe. Biểu đồ kỹ thuật tải mỗi 15 giây, dữ liệu tổng hợp chốt định kỳ 30 giây; giao diện kiểm tra tuổi mẫu mỗi giây.
- Mất API, mất kết nối, thiết bị không active hoặc mẫu quá `effective_offline_timeout_s` →
  **chưa xác định**, không biến mẫu trống cũ thành chỗ trống hiện tại.
- Timestamp backend là UTC; đồng hồ, bộ lọc và nhãn biểu đồ trên web dùng **UTC+7**.
- Biểu đồ kỹ thuật hiển thị số phút có xe theo giờ. Tỷ lệ tính theo thời gian đã quan sát, loại trừ khoảng chưa xác định; không phải số lượt xe hoặc doanh thu.
- Lịch sử chỉ thêm khi trạng thái đổi hoặc mỗi 60 giây, giữ 3 ngày. Sự kiện giữ 90 ngày; tổng hợp thời gian giữ 365 ngày. Xem [chính sách lưu trữ](../docs/STORAGE.md).
- Lịch sử tải 50 dòng/lần; tải thêm dùng `before_id`. Đang xem các trang cũ sẽ giữ tập kết quả
  để lần poll tiếp theo không xóa phần vừa tải thêm. Áp dụng lại bộ lọc để lấy trang mới nhất.
- Cảnh báo hiển thị tối đa 200 bản ghi gần nhất; lệnh 50, audit 200. CSV tối đa 10.000 dòng/lần,
  cần thu hẹp khoảng thời gian nếu dữ liệu vượt giới hạn.
- HTTP 202 chỉ là tạo lệnh. Chờ **Đã xác nhận** từ ACK trước khi coi cấu hình được áp dụng.
  Lệnh không có ACK được backend đánh dấu quá thời hạn sau các lần thử gửi.
- Cảnh báo bãi đầy cần tất cả ô đang có xe và dữ liệu còn hiệu lực. Cảnh báo mất kết nối bật riêng tại **Lệnh & cấu hình → Giám sát bãi đỗ**, mặc định tắt. Thiết bị phải từng gửi dữ liệu và đang active; backend chờ receiver ổn định trước khi báo mất kết nối. Cả hai loại tự kết thúc khi hết điều kiện. **Đánh dấu đã xem** chỉ ghi người/thời điểm xem, không đóng sự cố. Lệnh quá hạn xem trong lịch sử lệnh.

Token chỉ lưu trong `sessionStorage` của tab; không lưu mật khẩu. Đăng xuất xóa token, đóng tab kết thúc
bộ nhớ phiên của trình duyệt. JWT hết hạn hoặc quyền thay đổi sẽ yêu cầu đăng nhập lại.
Mật khẩu MQTT provision/rotate chỉ hiển thị ngay một lần trong hộp thoại, xóa khỏi DOM khi đóng.
Đổi mật khẩu MQTT không tự nạp lại firmware; phải cập nhật thiết bị để kết nối với mật khẩu mới.
Không có tài nguyên bên ngoài; frontend áp dụng CSP. Triển khai local chưa có HTTPS hoặc MQTT TLS.

## Kiểm tra

Kiểm tra Python từ thư mục gốc bằng virtualenv của repo. Node.js chỉ cần cho kiểm tra mã frontend:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest -q
node --check frontend/assets/app.js
node --check frontend/assets/core.js
node --check frontend/assets/views.js
node --check frontend/assets/viewer.js
node --test frontend/tests/core.test.js
```

Kiểm thử frontend bao gồm dữ liệu cũ/mất mạng thành unknown, tỷ lệ thời gian không tính unknown,
giao diện viewer tách biệt,
chuyển múi giờ, lọc đảo thời gian, escape nội dung và chặn trang admin cho viewer.
Kiểm thử backend bổ sung static/CSP, API vẫn bảo vệ, quyền hiệu lực, cảnh báo tự kết thúc, phạm vi người đã xem, mất kết nối và nhật ký bảo mật.

Để kiểm thử trình duyệt không tác động database hoặc broker thật:

```powershell
.\backend\.venv\Scripts\python.exe backend/tests/ui_server.py --port 8765
```

Mở **http://127.0.0.1:8765/**. Server dùng SQLite tạm và broker/ESP32 mô phỏng, xóa database khi dừng.
Các tài khoản thử `adminqa`, `operatorqa`, `limitedqa`, `viewerqa`, `observerqa` cùng mật khẩu
**`frontend-tests-only`**; đây chỉ là fixture, không được tạo ở bản chạy thật.
`limitedqa` không được gửi lệnh/cấu hình, `observerqa` không có thiết bị.
Fixture có endpoint admin `POST /__fixture/scenario` để đổi `online`, `full`, `ack_enabled`;
endpoint này **chỉ có khi chạy ui_server.py**, không được cài vào app thật.

Biển số, tính phí, OTA và số liệu đo độ trễ/thành công trên phần cứng thật
chưa được triển khai hoặc khẳng định bởi giao diện này.


Tổng quan hiển thị sơ đồ nhìn từ trên xuống: P1/P2, đường nội bộ, ô chờ vào/ra và hai thanh chắn.
Xe ở ô chờ lấy từ cảm biến D32/D33, độc lập với tín hiệu mở/đóng của servo; hai ô chờ không tính vào sức chứa.
Mất API hoặc dữ liệu cổng hết hiệu lực chuyển ô chờ và thanh chắn thành chưa xác định.
Admin chọn Tự động hoặc Điều khiển ngay dưới mỗi làn; Mở/Đóng chỉ bật trong chế độ Điều khiển
và khi dữ liệu còn hiệu lực. Lệnh chờ khóa thao tác tương ứng, kết quả cập nhật qua MQTT.
Thanh chắn minh họa tín hiệu điều khiển ESP32, chưa có cảm biến xác minh vị trí cơ khí thực tế.
Operator xem sơ đồ nhưng không có nút điều khiển; viewer giữ trang nhà xe riêng.
Backend từ chối mọi lệnh cổng của operator/viewer.
Firmware cũ hiện hướng dẫn nạp 0.4.0. Bộ kiểm thử trình duyệt mô phỏng hai cổng qua `ui_server.py`;
`POST /__fixture/scenario` nhận thêm entrance/exit để giả lập xe, không ảnh hưởng phần cứng thật.
