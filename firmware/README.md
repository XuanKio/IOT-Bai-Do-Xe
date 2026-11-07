# Firmware

Theo tên file người dùng yêu cầu, firmware chính được giữ tại
[`esp32_core/esp32_core.ino`](../esp32_core/esp32_core.ino), không tạo bản sao dễ bị lệch phiên bản.

Dependencies: ESP32 Arduino core 3.3.12, PubSubClient 2.8.0, WiFiManager 2.0.17, ArduinoJson 7.4.2.
Preferences và esp_random thuộc ESP32 core. Không commit config.local.h; chạy mqtt/Setup.ps1 để tạo.

Firmware 0.2.1 dùng ESPmDNS có sẵn trong ESP32 core để tìm `parkflow-iot.local` trước mỗi lần kết nối MQTT.
Backend phải chạy để quảng bá tên này. Nếu mDNS không phản hồi, firmware thử IP gần nhất hoặc IP dự phòng
trong `config.local.h`. Nạp bản mới một lần và cập nhật firewall bằng `mqtt/Enable-Firewall.cmd`;
sau đó đổi IP máy tính trong LAN không cần nạp lại firmware khi mDNS hoạt động.

Firmware **0.3.0** bổ sung LM393 cổng vào **GPIO32/D32** và cổng ra **GPIO33/D33**, LOW = có vật/xe.
P1 vẫn là GPIO27, P2 vẫn là GPIO26. Lọc tín hiệu cổng ổn định 50 ms, không chặn vòng lặp;
gửi snapshot khi thay đổi, giới hạn 10 bản tin/giây, ngoài chu kỳ heartbeat đang cấu hình.
Telemetry trên topic `iot/{device}/lm393` thêm `gate_sensors.entrance` / `gate_sensors.exit`,
mỗi cảm biến có `gpio`, `do`, `detected`. Cần chạy backend mới trước khi nạp firmware để schema nhận các trường mới.
Serial 115200 và Monitor đều hiển thị `VAO(D32)` / `RA(D33)`. Chưa đếm lượt xe qua cổng.

Kiểm thử bộ lọc trên máy tính (nếu có g++):

```powershell
g++ -std=c++11 -Wall -Wextra -pedantic firmware/tests/gate_sensor_test.cpp -o output/gate_sensor_test.exe
.\output\gate_sensor_test.exe
```


Firmware **0.4.0** bổ sung servo D18 (vào), D19 (ra). Mỗi cổng mặc định tự động, mở 90° khi LOW,
đóng 0° sau khi HIGH liên tục 3 giây; có xe trở lại sẽ hủy đếm ngược. Bộ điều khiển chạy trong
FreeRTOS task riêng mỗi 10 ms, không phụ thuộc MQTT hoặc backend. Hai góc và dải xung hiệu chỉnh
ở đầu sketch; nguồn servo ngoài và chung GND theo `hardware/README.md`.

Admin đổi chế độ `auto`/`manual` và mở/đóng từ trang Tổng quan. Chỉ chế độ được lưu NVS;
khởi động lại không khôi phục yêu cầu mở thủ công. Lệnh có boot ID, hạn dùng, revision riêng theo cổng,
cache kết quả để không thực hiện lại bản tin trùng. Không nhận thao tác Mở/Đóng khi đang tự động.
Telemetry thêm `gate_control.entrance` và `gate_control.exit`, bao gồm mode, target, servo_gpio,
pwm_ready, revision và close_remaining_ms. PWM thành công không xác minh chuyển động cơ khí.

Kiểm thử logic tự động/thủ công, xe trở lại, hai cổng độc lập và millis() tràn:

```powershell
g++ -std=c++11 -Wall -Wextra -pedantic firmware/tests/gate_controller_test.cpp -o output/gate_controller_test.exe
.\output\gate_controller_test.exe
```

Wi-Fi tắt modem sleep để giảm trễ thao tác web; TCP kết nối MQTT chờ tối đa 1500 ms mỗi lần. Bộ điều khiển cổng ở task riêng nên tiếp tục xử lý cảm biến và hẹn đóng trong lúc mạng kết nối lại.


Firmware **0.4.2** sửa luồng MQTT khi mạng chậm: TCP_NODELAY ngay sau TCP connect, MQTT chờ phản hồi
8 giây, kết nối TCP 4 giây, backoff 5–30 giây tính sau mỗi lần thử. Mỗi lần ghi TCP có deadline tổng
1500 ms; nếu ghi thiếu frame thì đóng socket trước khi kết nối lại, không nối tiếp frame mới vào gói dở.
ACK, trạng thái và telemetry dùng chung xử lý lỗi này. Serial thêm RSSI, MQTT_STATE và TX_MS.

```powershell
g++ -std=c++11 -Wall -Wextra -pedantic firmware/tests/mqtt_write_test.cpp -o output/mqtt_write_test.exe
.\output\mqtt_write_test.exe
.\backend\.venv\Scripts\python.exe mqtt/check_telemetry.py --seconds 40
```

`check_telemetry.py` chỉ subscribe, đếm mọi heartbeat, báo khoảng trống lớn nhất và số bản tin sai;
không ghi database hay phát telemetry. Monitor thông thường chỉ in khi trạng thái đổi hoặc mỗi 60 giây,
nên không dùng số dòng Monitor để suy ra số bản tin thực tế.


Firmware **0.4.3** thêm theo dõi giao nhận tự động: telemetry có `delivery_ack: true`; backend chỉ gửi
`telemetry_ack` kèm boot_id/seq sau khi chấp nhận dữ liệu. ESP32 từ chối ACK cũ hoặc seq chưa gửi.
Nếu không có ACK mới trong max(5 giây, 3 chu kỳ gửi + 2 giây), nó đóng socket và kết nối lại ngay một lần;
các lần kết nối thất bại tiếp tục backoff. Tác vụ servo vẫn chạy trong thời gian này.
Cần chạy backend mới trước khi nạp 0.4.3. Monitor/bộ đo chỉ subscribe, không tự phát ACK thay backend.
Serial có ACK_AGE_MS để phân biệt ghi thành công vào bộ đệm với dữ liệu đã được backend nhận.

```powershell
g++ -std=c++11 -Wall -Wextra -pedantic firmware/tests/telemetry_delivery_test.cpp -o output/telemetry_delivery_test.exe
.\output\telemetry_delivery_test.exe
```
