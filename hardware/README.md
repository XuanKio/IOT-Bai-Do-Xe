# Phần cứng hiện tại

- Một ESP32-D0WD-V3, nạp qua cổng COM được chọn trong Arduino IDE/CLI.
- Hai module hồng ngoại LM393: OUT ô P1 → D27, OUT ô P2 → D26, chung GND với ESP32.
- Hai module LM393 tại cổng: OUT/DO cổng vào → **D32 (GPIO32)**, OUT/DO cổng ra → **D33 (GPIO33)**; chung GND với ESP32. Hai cảm biến này nhận diện xe ở cổng, không làm tăng số ô đỗ P1/P2.
- Mức tín hiệu hiện tại: LOW = có xe, HIGH = trống. Ngưỡng cảm biến điều chỉnh bằng biến trở trên module.
- GPIO chỉ nhận logic 3.3V. Không đưa OUT 5V trực tiếp vào D27/D26. Cấp module 3V3 nếu module hỗ trợ,
  hoặc dùng chuyển mức phù hợp với đầu ra module.
- D4 giữ HIGH sau setup để duy trì chức năng đã yêu cầu; dùng làm tín hiệu, không dùng làm chân cấp nguồn module.
- Servo cổng vào: dây tín hiệu (cam/vàng) → **GPIO16/D16**. Servo cổng ra: dây tín hiệu → **GPIO19/D19**.
- Dây đỏ của hai servo → nguồn **5V ngoài phù hợp với servo**; dây nâu/đen → GND nguồn ngoài, nối chung GND với ESP32. Không cấp nguồn servo từ GPIO hoặc chân 3V3.
- Quy ước firmware: đóng 0°, mở 90°. Hiệu chỉnh `SERVO_CLOSED_DEGREES`, `SERVO_OPEN_DEGREES`, `SERVO_MIN_PULSE_US`, `SERVO_MAX_PULSE_US` theo servo thật, thử khi chưa gắn thanh chắn. Mặc định PWM 50 Hz, dải 500–2500 µs cho 0–180°; góc thực tế tùy servo.
- Tự động: D32 điều khiển servo D16, D33 điều khiển servo D19. LOW mở ngay sau lọc 50 ms; HIGH liên tục 3 giây thì đóng, xe xuất hiện lại sẽ hủy đếm ngược. Mỗi cổng có chế độ riêng.
- Điều khiển: admin chọn chế độ Điều khiển trên trang Tổng quan rồi bấm Mở/Đóng. Cảm biến không tự đổi vị trí trong chế độ này. Chế độ được lưu NVS; sau khởi động lại, cổng thủ công khởi tạo đóng, không phát lại yêu cầu mở cũ.
- Chưa có cảm biến vị trí thanh chắn; trạng thái trên web là tín hiệu điều khiển, không phải phép đo vị trí thực tế.

Nếu servo không phản ứng với cảm biến, kiểm tra chế độ trước: `MANUAL` bỏ qua cảm biến, kể cả sau khi nạp lại firmware vì chế độ được lưu NVS. Đổi cổng tương ứng sang **Tự động** trên web; với cổng vào có thể gửi `a` qua Serial Monitor 115200. Xem `SERVO_VAO(D16)` / `SERVO_RA(D19)` trong log để đối chiếu chế độ và PWM. Khi D32 thay đổi, chỉ servo D16 đổi mục tiêu; khi D33 thay đổi, chỉ servo D19 đổi mục tiêu.

Thông số tham khảo: [TowerPro SG90](https://towerpro.com.tw/product/sg90-7/), [Espressif servo/PWM](https://docs.espressif.com/projects/esp-iot-solution/en/latest/motor/servo.html).

Khi kiểm thử, che từng cảm biến riêng để đối chiếu P1/P2 trên Monitor và `/parking/slots`.
Với cổng vào/ra, che riêng từng cảm biến và xem `VAO(D32)` / `RA(D33)` trên Serial 115200 hoặc Monitor.
Trạng thái cổng được lọc ổn định 50 ms, gửi khi thay đổi (tối đa 10 bản tin/giây) và theo chu kỳ định kỳ.
Xem snapshot cổng tại `gate_sensors` của API `/telemetry/latest`; dữ liệu quá hạn/mất kết nối trả về chưa xác định.
Các cảm biến chỉ thể hiện có vật/xe tại vị trí theo dõi; chưa xác định biển số hay phương tiện cụ thể.
