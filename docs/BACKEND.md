# Backend v0.2

Đọc OpenAPI tại `/docs`. Mọi API quản lý cần Bearer JWT, trừ `/health` và `/auth/login`.
Tài khoản admin xem toàn hệ thống; operator xem các thiết bị có `DeviceGrant`. Viewer chỉ dùng `/parking/overview` theo grant và API tài khoản cá nhân, không truy cập API kỹ thuật.
Viewer luôn không được gửi lệnh, kể cả khi vô tình được gán cờ điều khiển.
Operator cần thêm `can_control` để ping, `can_configure` để cấu hình/rule. Chỉ admin quản lý tài khoản,
onboarding, cấp quyền, vị trí và vòng đời. Không có đăng ký công khai tự cấp quyền admin.

## Dashboard cùng origin

`GET /` phục vụ dashboard ParkFlow trong `frontend/`; `/assets/` phục vụ JS/CSS/SVG nội bộ.
Không cần Node.js, CDN hoặc cấu hình CORS để chạy giao diện. `/docs` vẫn dùng Swagger bình thường.
Trang giao diện có CSP, chống nhúng iframe và `nosniff`; trang gốc/phản hồi xác thực dùng `no-store`.

`GET /devices/{id}/permissions` trả quyền hiệu lực **của chính tài khoản đang gọi**:
`can_read`, `can_manage`, `can_control`, `can_configure`. API không tiết lộ grant của người khác;
thiết bị ngoài phạm vi trả 404. Đây là thông tin để giao diện bật/tắt thao tác, mọi API ghi vẫn kiểm tra quyền.

Phản hồi thiết bị thêm `report_interval_ms` và `effective_offline_timeout_s` để giao diện hết hạn
dữ liệu ngay cả giữa hai lần cập nhật. Giao diện truy vấn định kỳ 3 giây và hiển thị giờ UTC+7.
Xem [hướng dẫn frontend](../frontend/README.md).

## Luồng thiết bị

1. `POST /devices` với `code` duy nhất và `name`; trạng thái ban đầu `registered`.
2. `POST /devices/{id}/provision`: tạo tài khoản MQTT riêng và chuyển sang `provisioned`.
   Mật khẩu chỉ trả trong phản hồi này, không trả khi xem thiết bị hoặc audit log.
3. Cấu hình firmware bằng tài khoản đó. Username MQTT cũng là device ID và tên trong topic.
4. `PATCH /devices/{id}` với `{"status":"active"}` để đưa vào sử dụng.
5. `PUT /devices/{id}/grants/{user_id}` để cấp quyền xem/điều khiển/cấu hình.
6. `PATCH /devices/{id}/metadata` để ghi vị trí và lỗi/bảo trì.
7. `PUT /devices/{id}/slot` với `{"slot":"P1"}` hoặc P2 để gán ô. D27/P1, D26/P2 là hợp đồng firmware hiện tại.
8. `revoked` hoặc `decommissioned` gọi broker disableClient, ngắt các kết nối hiện có và chặn kết nối lại.
   API trả lỗi 503 nếu broker không xác nhận, không báo thu hồi thành công giả.

Thiết bị thật `esp32_01` được bootstrap sẵn ở trạng thái active với P1/P2 để giữ nguyên mô hình đã chạy.
Bootstrap không kích hoạt lại thiết bị đã bị thu hồi hoặc đổi mật khẩu của thiết bị đã onboarding.
`POST /devices/{id}/credentials/rotate` tạo mật khẩu mới; phải cập nhật lại trên thiết bị.

Vòng đời: registered → provisioned → active ↔ maintenance; có thể revoked rồi provisioned lại;
decommissioned là trạng thái cuối. Online/offline được tính riêng với trạng thái quản lý.

## Topic và dữ liệu

| Topic | Bên gửi | Nội dung |
|---|---|---|
| `iot/{device_id}/lm393` | ESP32 | Hai cảm biến, uptime, boot ID, seq, firmware/hardware, chu kỳ gửi |
| `iot/{device_id}/commands` | Backend | command_id, action, arguments, deadline, boot đích |
| `iot/{device_id}/ack` | ESP32 | command_id, succeeded/failed, kết quả đã áp dụng |
| `iot/{device_id}/status` | ESP32/broker will | online/offline, boot ID |

Payload telemetry:

```json
{"device_id":"esp32_01","uptime_s":12,"do":0,"detected":true,"do2":1,"detected2":false,
 "boot_id":"0123456789abcdef","seq":3,"firmware":"esp32_core-0.2.0","hardware":"ESP32-D0WD-V3","report_interval_ms":1000}
```

`do/detected` là P1; `do2/detected2` là P2. LOW=occupied. Backend kiểm tra topic/ID, kiểu và miền giá trị,
quan hệ DO/occupied. Thiết bị chưa được đăng ký/cấp quyền hoặc revoked bị từ chối. `simulator` có topic
và tài khoản riêng, chỉ admin xem; không cập nhật trạng thái bãi xe thật.

Một boot có seq tăng dần. Bản tin trùng, seq cũ hoặc boot đã được thay thế bị bỏ qua.
Firmware mới gửi đủ boot/seq; bản tin cũ không có cả hai trường vẫn được chấp nhận để tương thích.
Telemetry publish QoS 0, không retain; trạng thái mới nhất gửi theo chu kỳ, không có bộ đệm gửi bù.
Backend ghi timestamp nhận UTC. Uptime là giây từ khi thiết bị khởi động, không phải giờ đồng hồ.

## Cấu hình từ xa và xác nhận

```http
POST /devices/{id}/commands
Authorization: Bearer <token>
Content-Type: application/json

{"action":"configure","report_interval_ms":2000,"idempotency_key":"demo-config-01"}
```

HTTP 202 chỉ có nghĩa tạo yêu cầu, chưa có nghĩa ESP32 đã thực hiện. Theo dõi `GET /commands/{id}`.
Trạng thái: queued → sent → acknowledged/failed/timed_out/cancelled. Backend publish QoS 1,
thử tối đa ba lần, cách nhau hai giây, dùng lại command_id. ESP32 nhớ tám ACK gần nhất trong RAM;
hai lệnh hiện có đều idempotent. Cấu hình được lưu vào NVS và giữ sau khi khởi động lại.
Deadline theo boot ID/uptime giúp từ chối lệnh thuộc boot cũ hoặc đến quá hạn, không phụ thuộc Internet/NTP.

`{"action":"ping"}` kiểm tra phản hồi. Firmware 0.4.0 hỗ trợ thêm servo cổng vào/ra.
GET `/devices/{id}/configuration` cho biết chu kỳ đã ghi nhận và yêu cầu đang chờ.

## Cảnh báo và lịch sử

- GET/PUT `/devices/{id}/rules`: bật/tắt cảnh báo bãi đầy (`full_enabled`) và cảnh báo mất kết nối (`offline_enabled`), ngưỡng dữ liệu `offline_timeout_s` 5–120 giây. Admin hoặc operator có quyền cấu hình thiết bị được PUT; giá trị sai trả 422. Mặc định `offline_enabled=true`.
- Ngưỡng thực tế lấy max(ngưỡng cấu hình, ba chu kỳ gửi) để tránh báo mất kết nối sai khi tăng chu kỳ.
- Một cảnh báo đang diễn ra không bị tạo lại mỗi giây. Hết điều kiện thì ghi resolved_at.
- Cảnh báo `device_offline` được tạo khi thiết bị `active`, đã từng gửi dữ liệu (`last_seen`), bật `offline_enabled` và im lặng quá ngưỡng thực tế hoặc gửi trạng thái `offline` (LWT). Không tạo cảnh báo khi: thiết bị chưa từng gửi dữ liệu, trạng thái `registered/provisioned/maintenance/revoked/decommissioned`, MQTT receiver chưa sẵn sàng, hoặc chưa đủ một ngưỡng kể từ khi receiver sẵn sàng lại (tránh báo hàng loạt khi backend vừa khởi động). Trong các khoảng này cảnh báo đang mở được giữ nguyên (không resolve, không tạo trùng).
- `device_offline` tự resolved (`resolved_at`) khi có dữ liệu hợp lệ trở lại, khi thiết bị chuyển khỏi `active`, hoặc khi tắt `offline_enabled`. Mỗi sự cố là một cảnh báo riêng; sự cố sau tạo bản ghi mới và giữ lịch sử cũ. Dữ liệu cũ: các thiết bị tạo trước phiên bản này có `device_details.offline_alert = 0`; bật bằng `PUT /devices/{id}/rules` hoặc `UPDATE device_details SET offline_alert = 1`.
- Cảnh báo bãi đầy tự kết thúc khi điều kiện không còn (`resolved_at`). Danh sách `/alerts` trả cảnh báo `parking_full` và `device_offline`, kể cả lịch sử, kèm `kind`, `device_id`, `active`, `resolved_at`, `acknowledged`, `acknowledged_by` (ID người dùng) và `acknowledged_at`. Danh sách theo phạm vi thiết bị được cấp quyền.
- Thử nghiệm: thiết bị thật — ngắt nguồn/Wi-Fi ESP32, sau tối thiểu ngưỡng (mặc định 10 giây, ít nhất 3 chu kỳ gửi) `/alerts` có `device_offline`; cắm lại thì cảnh báo resolved. Thiết bị `simulator` không sinh cảnh báo offline.
- POST `/alerts/{alert_id}/acknowledge`: ghi nhận người đã xem/xử lý cảnh báo. Xác nhận **không** kết thúc cảnh báo; `active` và `resolved_at` vẫn do cơ chế tự động quyết định.
  - Admin xác nhận mọi cảnh báo; operator chỉ xác nhận cảnh báo của thiết bị được cấp quyền; viewer nhận 403; chưa đăng nhập bị từ chối.
  - Cảnh báo không tồn tại hoặc ngoài phạm vi thiết bị đều trả 404 giống nhau.
  - Idempotent: gọi lại trả 200 với người và thời điểm xác nhận đầu tiên, không ghi thêm audit log. Có thể xác nhận cảnh báo đã resolved; lịch sử không bị mất.
  - Audit log: `alerts.acknowledge:<alert_id>:device:<device_id>` (chỉ ghi lần xác nhận đầu tiên).
- `/parking/events` ghi initial/occupied/available/unknown/after_gap. Đây là thay đổi trạng thái ô,
  không phải nhận diện xe hoặc chứng minh chính xác lượt ra/vào qua cổng.
- Khi mất kết nối hoặc dữ liệu quá cũ, `/parking/slots` và `/dashboard` dùng unknown, không tính là trống.

## Truy vấn

- `/telemetry/latest?device_id=esp32_01`
- Snapshot mới nhất có `gate_sensors` (firmware 0.3.0+): `fresh`, `received_at`, `sensors.entrance` và `sensors.exit`. Mỗi cảm biến gồm `gpio`, `do`, `detected`; khi mất kết nối hoặc quá hạn, `do` và `detected` là null. Firmware cũ chưa gửi dữ liệu cổng trả `gate_sensors: null`. Dữ liệu mới nhất nằm trong bảng `live_gate_sensors`, tách khỏi chỗ đỗ và lịch sử P1/P2; không suy diễn lượt xe.
- `/telemetry?device_id=esp32_01&limit=50&before_id=123&from_at=...&to_at=...`
- `/telemetry/statistics`: đếm mẫu theo giờ UTC và ô; phần trăm là phần trăm **số mẫu**, không phải thời gian đỗ.
- `/telemetry/export.csv`: tối đa 10000 dòng mỗi lần, thu hẹp khoảng thời gian để xuất tiếp; ghi audit log `telemetry.export_csv:<device_id>`.
- `GET /audit-logs?limit=50`: chỉ dành cho `admin` (`limit` 1–200; `operator` và `viewer` nhận 403). Ghi nhận các thao tác xác thực và quản trị quan trọng (`auth.login`, `auth.login_failed`, `auth.logout`, `auth.password_changed`, `auth.password_change_failed`, `users.create:*`, `users.update:*`, `devices.create:*`, `devices.provision:*`, `devices.rotate_credentials:*`, `devices.status:*`, `devices.metadata:*`, `devices.grant:*`, `devices.ungrant:*`, `devices.assign_slot:*`, `devices.rules:*`, `commands.create:*`, `alerts.acknowledge:*`, `telemetry.export_csv:*`), không lưu mật khẩu, hash, JWT hay thông tin bí mật MQTT. Xem [SECURITY_TESTS.md](SECURITY_TESTS.md).

from_at/to_at dùng ISO 8601 kèm múi giờ, ví dụ `2026-10-24T08:00:00+07:00`; client phải URL-encode dấu +.
Dữ liệu nhạy cảm: tên tài khoản, mật khẩu băm, quyền thiết bị. Không thu biển số/ảnh/vị trí GPS cá nhân.
Không commit `.env`, `config.local.h`, `mqtt/runtime`, database hoặc bản sao lưu. Triển khai local chưa có TLS/HTTPS.

## Chính sách dữ liệu mới

Xem [STORAGE.md](STORAGE.md). `live_telemetry` lưu trạng thái hiện tại độc lập với lịch sử.
`/telemetry/latest` lấy trạng thái này; lịch sử/CSV chỉ chứa mẫu thay đổi hoặc checkpoint 60 giây, giữ 3 ngày.
`/parking/utilization` trả thời gian quan sát theo giờ (có xe/trống/chưa xác định), làm tròn bộ lọc ra toàn bộ giờ giao nhau.
`/telemetry/statistics` cũ vẫn đếm mẫu được lưu và không dùng làm tỷ lệ thời gian.
`/storage/policy` dành cho admin. Viewer bị từ chối các API thiết bị, telemetry, cấu hình, lệnh và cảnh báo kỹ thuật bằng 403.


## Cổng vào / ra (firmware 0.4.0)

GET `/devices/{id}/gates`: snapshot cổng theo quyền thiết bị, có `fresh`, `valid_until`, lệnh chờ/kết quả gần nhất.
Trạng thái mất hiệu lực trả mode/target null. `position_verified` luôn false vì chưa có phản hồi vị trí.
Mỗi cổng có thêm `detected` cho ô chờ tương ứng (D32/D33), độc lập với `target` của servo.
Chỉ trả true/false khi cảm biến cùng boot và cùng bản tin telemetry còn hiệu lực; thiếu, cũ hoặc mất kết nối trả null.
Hai ô chờ không tính vào sức chứa P1/P2. Frontend dùng snapshot này cho sơ đồ admin/operator.
POST `/devices/{id}/commands` chỉ dành cho admin với hai action mới:

```json
{"action":"gate_mode","gate":"entrance","mode":"manual","timeout_s":5,"idempotency_key":"mode-in-1"}
```

```json
{"action":"gate","gate":"entrance","target":"open","timeout_s":5,"idempotency_key":"open-in-1"}
```

Gate là entrance/exit, mode là auto/manual, target là open/closed. Thao tác mở/đóng yêu cầu snapshot mới và
mode manual. Mỗi cổng chỉ có một lệnh chờ; backend cấp revision tăng dần theo cổng, xác thực ACK theo
boot ID, gate, revision và kết quả. Đổi boot/mất kết nối/thu hồi quyền admin sẽ hủy lệnh đang chờ.
Tự động mở/đóng chạy tại ESP32; không tạo cảnh báo mới ngoài bãi đầy. Bảng mới `live_gate_control` và
`gate_command_counters` được thêm khi backend khởi động, không đổi các bảng dữ liệu cũ.


Firmware 0.4.3 có thể yêu cầu phản hồi giao nhận bằng `delivery_ack: true` trong telemetry.
Sau khi lưu dữ liệu hợp lệ, MQTT receiver chính phát `{"action":"telemetry_ack","boot_id":"...","seq":123}`
qua `iot/{device}/commands`. Chỉ receiver backend bật `ack_telemetry`; monitor không phát phản hồi.
Phản hồi này tự động, không tạo bản ghi lệnh người dùng, cảnh báo hay thao tác xác nhận trên giao diện.
