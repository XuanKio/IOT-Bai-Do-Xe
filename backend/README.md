# Backend bãi đỗ xe IoT

Nguyên mẫu FastAPI cho một bãi xe, hai chỗ P1/P2. Admin quản lý toàn hệ thống; operator chỉ truy cập thiết bị đã được cấp quyền; viewer dùng API nhà xe tối giản theo grant. Chưa hỗ trợ nhiều bãi xe độc lập.

## Chạy trên PowerShell

Chạy các lệnh sau từ thư mục `backend`:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
$env:JWT_SECRET = "thay-bang-chuoi-ngau-nhien-dai-it-nhat-32-ky-tu"
.\.venv\Scripts\python.exe -m app.create_admin
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Mở http://127.0.0.1:8000/ để dùng dashboard ParkFlow hoặc http://127.0.0.1:8000/docs để thử API.
Dashboard được FastAPI phục vụ trực tiếp, không cần build hoặc chạy server khác.
Trên Swagger, gọi `/auth/login`, sao chép `access_token`, bấm **Authorize** và dán token.
Không có tài khoản hoặc mật khẩu mặc định.

Biến môi trường được đọc từ tiến trình; `.env.example` chỉ là mẫu, chưa tự nạp file `.env`. Nếu không đặt JWT_SECRET, khóa ngẫu nhiên được tạo mỗi tiến trình, token mất hiệu lực khi khởi động lại; cần đặt khóa cố định khi chạy thật hoặc nhiều worker.

SQLite được dùng để chạy local không cần cài database. File `parking.db` được tạo tại thư mục chạy lệnh. Schema hiện được tạo bằng SQLAlchemy `create_all`; chưa có migration. Muốn chuyển PostgreSQL cần cài driver, cấu hình DATABASE_URL và bổ sung migration.

## Chức năng đã có

- Đăng nhập JWT, đăng xuất thu hồi toàn bộ token của tài khoản, đổi mật khẩu và xem hồ sơ.
- Admin tạo tài khoản, phân vai trò admin/operator/viewer, khóa tài khoản. Không được tự khóa hoặc hạ quyền chính mình.
- Đăng ký thiết bị, xem danh sách, cập nhật trạng thái theo vòng đời. Decommissioned là trạng thái kết thúc.
- Hai chỗ đỗ mặc định có trạng thái unknown; dashboard không tính unknown là chỗ trống.
- Chỉ cảnh báo bãi đầy, tự kết thúc, không cần xác nhận; audit log dành cho admin.
- Swagger/OpenAPI và health check.

## Quyền

| Chức năng | Admin | Operator | Viewer |
|---|---|---|---|
| Xem nhà xe tối giản `/parking/overview` | Có | Theo scope | Theo scope |
| Dashboard kỹ thuật, thiết bị, telemetry/CSV, cảnh báo | Có | Theo scope | Không |
| Lịch sử cảnh báo bãi đầy | Có | Theo scope | Không |
| Ping/cấu hình có ACK | Có | Theo quyền thiết bị | Không |
| Quản lý tài khoản, thiết bị, audit log | Có | Không | Không |

## Tích hợp phần cứng và frontend

Đã có MQTT nhận hai LM393 từ `esp32_01`: D27 là ô P1, D26 là ô P2. Broker Mosquitto portable có tài khoản/ACL riêng; backend lưu lịch sử từng ô và cập nhật `/parking/slots`, `/dashboard`. Mẫu quá ngưỡng offline (mặc định 10 giây, tối thiểu ba chu kỳ gửi) hoặc broker mất kết nối được coi là unknown. Xem `../mqtt/README.md` để chạy broker, backend, monitor và nạp firmware. Dữ liệu mô phỏng dùng thiết bị/topic riêng, không ghi đè trạng thái chỗ đỗ thật. Barie chưa được tích hợp.

Backend v0.2 bổ sung cấp mật khẩu MQTT riêng qua onboarding, phân quyền theo từng thiết bị, thu hồi/decommission thực sự trên broker Dynamic Security, thông tin vị trí/hardware/firmware, cảnh báo bãi đầy tự kết thúc, lịch sử đổi trạng thái ô, bộ lọc thời gian, thống kê và CSV. Lệnh ping/cấu hình chu kỳ gửi có retry, timeout và ACK từ ESP32; HTTP 202 chưa có nghĩa lệnh đã thực hiện. Xem `../docs/BACKEND.md` để dùng API. Dashboard trong `../frontend/` hỗ trợ các chức năng này theo quyền tài khoản. Servo được tạm hoãn theo yêu cầu; chưa có nhận diện xe hoặc tính phí.

Chưa có TLS deployment, rate limiting đăng nhập hoặc quy trình khôi phục mật khẩu. Chạy local trước;
cần đo kiểm với phần cứng thật và hoàn thiện hồ sơ nộp theo [đối chiếu yêu cầu](../docs/REQUIREMENTS.md).

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Kiểm thử dùng SQLite tạm riêng; bao gồm từ chối mật khẩu sai, phân quyền, thu hồi token, trùng mã thiết bị, chuyển trạng thái và dữ liệu chỗ đỗ chưa xác định.

Xem [chính sách dữ liệu](../docs/STORAGE.md): SQLite giữ nguyên, dữ liệu hiện tại tách khỏi lịch sử,
mẫu thay đổi/định kỳ giữ 3 ngày, sự kiện 90 ngày, tổng hợp thời gian 365 ngày.
