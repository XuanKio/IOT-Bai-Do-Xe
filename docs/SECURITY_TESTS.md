# Báo Cáo Kiểm Thử Bảo Mật & Audit Log Backend (TV2)

Tài liệu này mô tả phạm vi kiểm thử bảo mật tự động và đối chiếu Audit Log cho phần Backend (`FastAPI` + `SQLite`) của hệ thống bãi đỗ xe thông minh **ParkFlow**.

## 1. Các mối đe dọa và rủi ro đã kiểm tra

1. **Giả mạo hoặc tái sử dụng phiên xác thực (JWT Authentication Risks):**
   - Truy cập API bảo vệ không có Bearer token hoặc định dạng header sai.
   - Token giả mạo chữ ký (sai khóa bí mật `JWT_SECRET`), dùng thuật toán `alg="none"`, thiếu hoặc sai kiểu claim `sub`/`ver`, hoặc token đã hết hạn (`exp`).
   - Tiếp tục sử dụng JWT cũ sau khi người dùng đã đăng xuất (`POST /auth/logout`), đổi mật khẩu (`POST /auth/password`), bị khóa tài khoản (`active=false`), hoặc bị thay đổi vai trò (`role`).
2. **Leo thang đặc quyền & vượt phạm vi thiết bị (RBAC & IDOR Risks):**
   - `viewer` cố gắng truy cập API kỹ thuật, danh sách thiết bị, telemetry, cấu hình, điều khiển thiết bị/cổng, xác nhận cảnh báo hoặc xem `/audit-logs` (kể cả khi bản ghi `DeviceGrant` trong DB có cờ `can_control`/`can_configure`).
   - `operator` cố gắng gọi các API quản trị (`POST/GET/PATCH /users`, `POST/PATCH /devices`, `provision`, `rotate`, `grants`, `slot`, điều khiển cổng `gate`/`gate_mode`, `/audit-logs`, `/storage/policy`).
   - `operator` truy cập thiết bị hoặc xác nhận cảnh báo ngoài phạm vi `DeviceGrant` (kiểm tra chống IDOR: trả `404` đồng nhất với tài nguyên không tồn tại, không lộ sự tồn tại của thiết bị/cảnh báo).
   - Phân tách cờ quyền chi tiết của `operator`: chỉ đọc (`can_control=false, can_configure=false`), chỉ điều khiển (`can_control=true`), chỉ cấu hình (`can_configure=true`).
3. **Thiếu vết kiểm toán hoặc rò rỉ bí mật trong nhật ký (Audit Log Integrity & Secret Leakage):**
   - Đảm bảo mọi thao tác nhạy cảm (đăng nhập thành công/thất bại với tài khoản tồn tại, đăng xuất, đổi mật khẩu thành công/thất bại, tạo/cập nhật người dùng, tạo/cấp phát/xoay vòng khóa/đổi trạng thái/cập nhật metadata/gán quyền/gán ô/cập nhật rule thiết bị, phát lệnh điều khiển, xác nhận cảnh báo, xuất CSV telemetry) đều ghi nhận đúng `actor_id` và `action`.
   - Đảm bảo các thao tác lặp lại idempotent (`POST /alerts/{id}/acknowledge`, `POST /devices/{id}/commands` trùng `idempotency_key`), thao tác cập nhật trạng thái thiết bị trùng trạng thái hiện tại (no-op `PATCH /devices/{id}`), hoặc các thao tác thất bại (`400`/`403`/`404`/`409`/`422`/`503`) không sinh bản ghi audit thành công giả hoặc trùng lặp.
   - Đảm bảo không bao giờ ghi mật khẩu thuần, chuỗi băm Argon2 (`$argon2...`), JWT access token, hoặc `mqtt_password` vào bảng `audit_logs` hay phản hồi lỗi.

## 2. Danh mục Audit Log (`audit_logs`)

| Nhóm | Hành động (`action`) | Endpoint kích hoạt | Ghi chú bảo mật |
|---|---|---|---|
| Xác thực | `auth.login` | `POST /auth/login` | Ghi khi đăng nhập thành công |
| Xác thực | `auth.login_failed` | `POST /auth/login` | Ghi khi tài khoản tồn tại nhưng mật khẩu sai hoặc tài khoản bị khóa (`active=false`). Tài khoản không tồn tại không ghi vào `audit_logs` do ràng buộc khóa ngoại `actor_id -> users.id` |
| Xác thực | `auth.logout` | `POST /auth/logout` | Tăng `token_version`, thu hồi tức thì mọi JWT cũ |
| Xác thực | `auth.password_changed` | `POST /auth/password` | Tăng `token_version`, không ghi mật khẩu cũ/mới |
| Xác thực | `auth.password_change_failed` | `POST /auth/password` | Ghi khi nhập sai mật khẩu hiện tại (`400`) |
| Người dùng | `users.create:<username>` | `POST /users` | Chỉ `admin`; rollback nếu trùng `username` (`409`) |
| Người dùng | `users.update:<user_id>` | `PATCH /users/{user_id}` | Chỉ `admin`; tăng `token_version` của tài khoản đích |
| Thiết bị | `devices.create:<code>` | `POST /devices` | Chỉ `admin`; rollback nếu trùng `code` (`409`) |
| Thiết bị | `devices.provision:<device_id>` | `POST /devices/{id}/provision` | Chỉ ghi khi broker xác nhận thành công; không ghi `mqtt_password` |
| Thiết bị | `devices.rotate_credentials:<device_id>` | `POST /devices/{id}/credentials/rotate` | Chỉ ghi khi broker xác nhận thành công; không ghi `mqtt_password` |
| Thiết bị | `devices.status:<device_id>:<status>` | `PATCH /devices/{id}` | Chỉ ghi khi trạng thái thực sự thay đổi và broker xác nhận |
| Thiết bị | `devices.metadata:<device_id>` | `PATCH /devices/{id}/metadata` | Chỉ `admin` |
| Thiết bị | `devices.grant:<device_id>:user:<user_id>` | `PUT /devices/{id}/grants/{uid}` | Chỉ `admin` |
| Thiết bị | `devices.ungrant:<device_id>:user:<user_id>` | `DELETE /devices/{id}/grants/{uid}` | Chỉ `admin` |
| Thiết bị | `devices.assign_slot:<device_id>:<slot>` | `PUT /devices/{id}/slot` | Chỉ `admin` |
| Thiết bị | `devices.rules:<device_id>` | `PUT /devices/{id}/rules` | `admin` hoặc `operator` có `can_configure` |
| Lệnh | `commands.create:<device_id>:<cmd_id>:<action>` | `POST /devices/{id}/commands` | Không ghi trùng khi gọi lại cùng `idempotency_key` |
| Cảnh báo | `alerts.acknowledge:<alert_id>:device:<device_id>` | `POST /alerts/{id}/acknowledge` | Chỉ ghi ở lần xác nhận đầu tiên (idempotent) |
| Dữ liệu | `telemetry.export_csv:<device_id>` | `GET /telemetry/export.csv` | Ghi khi người dùng đủ quyền xuất dữ liệu CSV hợp lệ |

## 3. Các Test Case Bảo Mật Tự Động & Kết Quả

File kiểm thử: `backend/tests/test_security_audit.py`

Lệnh chạy kiểm thử:

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_security_audit.py -v
```

| Mã nhóm | Test function | Mục tiêu kiểm chứng | Kết quả mong đợi | Kết quả thực tế | Trạng thái |
|---|---|---|---|---|---|
| **S1** | `test_s1_jwt_missing_malformed_wrong_signature_wrong_alg_and_claims` | Từ chối truy cập thiếu token, token sai định dạng, sai chữ ký, `alg=none`, sai `sub`/`ver`; không lộ secret | HTTP `401`/`403`, không rò rỉ `SECRET` hoặc `$argon2` | Đúng như mong đợi | **PASS** |
| **S1** | `test_s1_jwt_expiration_and_revocation_on_logout_password_deactivate_and_role_change` | Từ chối token hết hạn (`exp`), thu hồi token tức thì sau logout, đổi mật khẩu, đổi vai trò hoặc khóa tài khoản | HTTP `401` ngay lập tức với token cũ | Đúng như mong đợi | **PASS** |
| **S2** | `test_s2_viewer_rbac_restrictions_and_grant_scope` | Cô lập quyền `viewer`: chỉ dùng `/auth/*` và `/parking/overview` theo grant; chặn toàn bộ 31 endpoint kỹ thuật/quản trị | HTTP `200` trên `/parking/overview` (theo scope), HTTP `403` trên mọi API kỹ thuật/quản trị | Đúng như mong đợi | **PASS** |
| **S2** | `test_s2_operator_rbac_and_granular_device_grants_anti_idor` | Chặn `operator` gọi API `admin` (`403`), ẩn thiết bị/cảnh báo ngoài grant (`404` chống IDOR), kiểm tra cờ `can_control` và `can_configure` | HTTP `403` cho API admin/thiếu cờ; HTTP `404` đồng nhất cho thiết bị/cảnh báo ngoài grant | Đúng như mong đợi | **PASS** |
| **S2** | `test_s2_audit_logs_endpoint_access_and_validation` | Bảo vệ endpoint `GET /audit-logs` (chỉ `admin`), kiểm tra giới hạn `limit` `1..200` | `admin` `200`, `operator`/`viewer` `403`, chưa đăng nhập `401`/`403`, sai `limit` `422` | Đúng như mong đợi | **PASS** |
| **S3** | `test_s3_complete_audit_trail_for_critical_actions` | Đối chiếu đầy đủ các hành động trong `audit_logs` và kiểm tra không rò rỉ mật khẩu/hash/token/MQTT password | Đủ 19 mẫu hành động với đúng `actor_id`, không có chuỗi bí mật trong log | Đúng như mong đợi | **PASS** |
| **S3** | `test_s3_idempotency_noop_and_failed_actions_do_not_duplicate_or_pollute_audit` | Không nhân bản audit khi gọi lại idempotent/no-op và không ghi audit thành công giả khi thao tác lỗi (`400`/`404`/`409`/`422`/`503`) | Chỉ 1 bản ghi cho idempotent/no-op; 0 bản ghi thừa khi thao tác thất bại | Đúng như mong đợi | **PASS** |
| **S4** | `test_s4_security_regression_e1_e2_alerts_and_device_lifecycle` | Kiểm thử hồi quy tích hợp E1 (`acknowledge`), E2 (`device_offline`), `parking_full` và thu hồi thiết bị (`revoked`) | Cảnh báo tạo, xác nhận, tự resolve và thu hồi quyền broker chính xác | Đúng như mong đợi | **PASS** |

## 4. Giới hạn phạm vi & Đề xuất kiến trúc (Limitations & Recommendations)

1. **Môi trường kiểm thử tự động (`FakeBroker` vs Phần cứng thực):**
   - Các bài kiểm thử trong `backend/tests/test_security_audit.py` chạy tự động trên cơ sở dữ liệu SQLite cô lập và `FakeBroker` (giả lập giao tiếp quản trị Dynamic Security của Mosquitto và MQTT Receiver).
   - Việc kiểm chứng xác thực/ACL MQTT thực tế giữa mạch `ESP32` và tiến trình `Mosquitto` cũng như cấu hình TLS/HTTPS khi triển khai thực tế thuộc phạm vi kiểm thử tích hợp hệ thống / triển khai (TV1 & TV3).
2. **Ghi nhận đăng nhập thất bại với `username` không tồn tại (`POST /auth/login`):**
   - **Hiện trạng:** Khi `username` tồn tại trong bảng `users` nhưng sai mật khẩu hoặc tài khoản đang bị khóa (`active=false`), hệ thống ghi nhận `auth.login_failed` với `actor_id = user.id`. Khi `username` không tồn tại trong CSDL, hệ thống trả về cùng thông báo `401 "Invalid credentials"` (chống dò tìm tài khoản) nhưng **không** thể ghi vào bảng `audit_logs` vì cột `actor_id` có ràng buộc `INTEGER NOT NULL REFERENCES users(id)` (`PRAGMA foreign_keys=ON`). Hệ thống tuyệt đối không tạo bản ghi user giả để tránh làm bẩn bảng `users` và tránh rủi ro tấn công làm đầy CSDL (storage exhaustion DoS).
   - **Phương án đề xuất khi mở rộng:** (a) Ghi nhận sự kiện đăng nhập thất bại của username không tồn tại vào luồng nhật ký bảo mật ứng dụng / Reverse Proxy kèm địa chỉ IP nguồn và áp dụng rate-limiting theo IP; hoặc (b) Thực hiện migration schema trong phiên bản sau cho phép `actor_id` nhận `NULL` đối với sự kiện chưa định danh, bổ sung trường `ip_address` / `context` giới hạn độ dài kèm chính sách tự động dọn dẹp (`retention policy`).
3. **Quản lý khóa ký `JWT_SECRET` giữa môi trường Test/Dev và Production:**
   - **Hiện trạng:** Tại `backend/app/main.py`, `SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)` không dùng chuỗi mặc định tĩnh trong mã nguồn. Khi thiếu biến môi trường `JWT_SECRET`, mỗi tiến trình tự sinh một khóa ngẫu nhiên 48 byte (384 bit entropy) bằng CSPRNG — đảm bảo không thể giả mạo chữ ký offline khi chạy đơn tiến trình (dev/local), còn trong bộ công cụ chạy thật (`mqtt/configure.py`) khóa `jwt_secret` 48 byte (`secrets.token_hex(48)`) được sinh tự động vào `mqtt/runtime/backend.env`. Bộ kiểm thử (`backend/tests/conftest.py`) đặt khóa riêng cho môi trường pytest.
   - **Lưu ý triển khai Production:** Cần đặt cố định `JWT_SECRET` có độ dài tối thiểu 32 ký tự ngẫu nhiên (không dùng lại giá trị mẫu trong `.env.example` / `README.md`) để duy trì phiên qua các lần khởi động lại hoặc khi chạy nhiều worker.

