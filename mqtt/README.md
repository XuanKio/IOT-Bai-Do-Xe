# ESP32 LM393 qua MQTT

Dia chi broker hien tai nam trong `mqtt/runtime/connection.json`, cong mac dinh 1884. Cong 1883 dang do dich vu khac su dung.
Topic thiet bi that: `iot/esp32_01/lm393`. Code duy nhat can nap: `esp32_core/esp32_core.ino`.

## Chay tren may tinh

- Mo `Start-IOT.cmd` de bat broker va backend. Hai tien trinh chay an, khong can giu cua so nay.
- Mo `Monitor.cmd` de xem du lieu truc tiep, kem gio Viet Nam va uptime ESP32. Ctrl+C de dung monitor.
- Mo `Enable-Firewall.cmd`, chap nhan UAC cua Windows mot lan de mo cong MQTT tu mang LAN.
  Script mo TCP 1884 cho Mosquitto va UDP 5353 cho Python/mDNS, chi nhan tu LocalSubnet.
  Quy tac ap dung cho cac IP tren may nen khong can tao lai khi DHCP doi IP.
  Khong tat firewall. Quyen Administrator la yeu cau cua Windows de them quy tac firewall.
- Dung dich vu: `powershell -ExecutionPolicy Bypass -File .\mqtt\Stop-IOT.ps1`.

Tat may/ngat Wi-Fi thi broker local khong con truy cap duoc. Khong co tac vu tu khoi dong cung Windows.

## Nap ESP32

Thu vien da cai tren may: PubSubClient 2.8.0, WiFiManager 2.0.17, ArduinoJson 7.4.2. ESP32 Arduino core: 3.3.12.

1. Cam ESP32 bang cap USB du lieu. Mo `esp32_core/esp32_core.ino` bang Arduino IDE.
2. Chon board ESP32 phu hop (thuong ESP32 Dev Module) va dung cong COM, sau do Upload.
   File `config.local.h` da duoc tao cung thu muc, khong can nhap tai khoan MQTT.
3. Mo Serial Monitor 115200. Lan dau, dung dien thoai ket noi Wi-Fi `ESP32-IOT-Setup`.
   Mat khau mang cau hinh o `mqtt/runtime/THONG_TIN_DANG_NHAP.txt` va duoc in tren Serial.
4. Mo `http://192.168.4.1`, chon Wi-Fi **2.4 GHz** cung mang LAN voi may tinh va nhap mat khau Wi-Fi.
   May tinh co the dung bang tan 5 GHz neu router cho hai bang tan truy cap cung mang LAN.
   Khong dung guest Wi-Fi co client isolation.
5. Khi Serial hien `MQTT OK` va `MQTT=DA GUI`, xem ket qua o `Monitor.cmd`.
   Go `w` va Enter tren Serial de mo lai cong cau hinh Wi-Fi.

Co the nap bang CLI:

```powershell
.\mqtt\Upload-ESP32.ps1 -Port COM5
```

Thay COM5 bang cong that. De chi bien dich: `.\mqtt\Upload-ESP32.ps1 -CompileOnly`.
Trong luc firmware thu ket noi lai broker, dong Serial co the tre hon 1 giay do timeout ket noi ngan.

## Dau day

- O do 1 (P1): DO/OUT -> D27. O do 2 (P2): DO/OUT -> D26. GND hai cam bien -> GND ESP32.
- LOW (0V) = co vat can; HIGH (khoang 3.3V) = khong co vat can.
- **Khong noi OUT 5V truc tiep vao D27.** Cap module 3V3 neu module ho tro, hoac dung bo chuyen muc.
- D4 giu HIGH sau setup, la tin hieu dieu khien; khong dung lam nguon cap cho module.
- Cam bien cong vao DO/OUT -> D32, cong ra -> D33. Servo cong vao tin hieu -> D16, cong ra -> D19; nguon servo 5V ngoai va chung GND voi ESP32.
- Che do AUTO: D32 dieu khien D16, D33 dieu khien D19. Che do MANUAL bo qua cam bien va cho lenh tu web. Che do duoc luu NVS, khong bi xoa khi nap lai firmware.
- Firmware 0.4.4 cho phep gui `a` va Enter qua Serial 115200 de luu cong vao sang AUTO; log hien che do, tan so va duty cua tung servo. Xem `../firmware/README.md`.

## Backend va thu du lieu

Mo dashboard **`http://127.0.0.1:8000/`**. Tai khoan `mqtt_admin` va mat khau ngau nhien nam trong
`mqtt/runtime/THONG_TIN_DANG_NHAP.txt`. Giao dien chay cung backend, khong can cai Node.js.
Swagger API van o `http://127.0.0.1:8000/docs`; goi `/auth/login`, dung access_token o nut Authorize.

- `/health`: trang thai ket noi broker va dang ky topic (khong dong nghia ESP32 da gui du lieu).
- `/telemetry/latest`: mau moi nhat cua `esp32_01`; `null` neu chua co mau that.
- `/telemetry?limit=50`: lich su. Du lieu luu trong `backend/parking.db`, bang `sensor_telemetry`.
- `received_at` la gio UTC khi may tinh nhan; monitor doi sang UTC+7.
- `uptime_s` la thoi gian tu khi ESP32 khoi dong, khong phai gio dong ho.
- `fresh` chi true neu broker dang ket noi, da subscribe va mau con trong nguong offline cau hinh.
  Ban v0.2 dung max(offline_timeout_s, ba chu ky gui); mac dinh nguong 10 giay.
  Khi offline, gia tri cu van co trong lich su; khong coi no la phep do moi.
- P1 = D27, P2 = D26. MQTT gui `do`/`detected` cho P1, `do2`/`detected2` cho P2.
  `/telemetry/latest` va lich su co them mang `slots`; mau cu van giu nguyen trong database.
  `/parking/slots` va `/dashboard` tu cap nhat tu du lieu thiet bi that; du lieu mo phong khong doi cho do.
  Mat ket noi hoac mau qua nguong offline thi cho do hien `unknown`, khong tinh thanh cho trong.
  Lich su tung o luu them trong bang `sensor_slot_readings`. Dieu khien barie dung lenh `gate_mode`/`gate` danh cho admin, co ACK; firmware tu anh xa `entrance`/`exit` sang GPIO16/GPIO19.
- Firmware publish QoS 0, khong retain: gui trang thai moi nhat moi giay, khong luu bu du lieu khi offline.

Thu ma khong can ESP32:

```powershell
.\backend\.venv\Scripts\python.exe .\mqtt\simulate.py --count 4
```

Du lieu thu co nhan **MO PHONG**, topic `iot/simulator/lm393`, thiet bi `simulator`;
khong ghi de thiet bi that. Xem API bang `device_id=simulator`.

Kiem tra broker/authentication/ACL va MQTT -> database -> API:
`.\backend\.venv\Scripts\python.exe .\mqtt\check_setup.py`.

## Cai lai / doi IP

Firmware 0.2.1+ tim broker bang `parkflow-iot.local` (mDNS) truoc moi lan ket noi MQTT.
Backend Python quang ba IPv4 LAN va kiem tra thay doi moi 5 giay. Broker lang nghe IPv4 tren may
thay vi gan vao mot IP cu the. Mat khau va quyen MQTT duoc giu nguyen.

De nang cap: cai dependencies backend, nap firmware moi mot lan va chay lai `Enable-Firewall.cmd` mot lan.
Khoi dong lai backend/broker de nap thay doi. Sau do doi IP may tinh trong LAN khong can nap lai ESP32.
Backend phai dang chay; Wi-Fi/router phai cho phep multicast mDNS va hai thiet bi truy cap cung LAN.
Neu mDNS khong phan hoi, ESP32 thu IP gan nhat hoac `MQTT_HOST` trong `config.local.h`.
DHCP reservation tren router van la phuong an huu ich neu mang chan multicast.

Khi khoi dong broker, `Start-IOT.ps1` van cap nhat IP du phong trong cac file cau hinh theo LAN hien tai.

Cai lai cau hinh khi can:

```powershell
.\mqtt\Stop-IOT.ps1
.\mqtt\Setup.ps1
.\mqtt\Start-IOT.ps1
```

Setup tu lay IPv4 mang hien tai va giu nguyen mat khau da tao.

`.tools/` chua ban portable Mosquitto 2.1.2 va 7-Zip 26.05 lay tu trang chinh thuc, khong cai dich vu he thong.
`mqtt/runtime/` va `esp32_core/config.local.h` chua thong tin rieng, da loai khoi Git.
MQTT TCP nay danh cho thu nghiem mang LAN tin cay; chua cau hinh TLS/truy cap Internet.
Backend da co chinh sach luu/don: mau thay doi hoac checkpoint 60 giay giu 3 ngay,
su kien giu 90 ngay, tong hop thoi gian giu 365 ngay. Trang thai hien tai van cap nhat moi ban tin.
Xem `../docs/STORAGE.md`.

Backend v0.2 dung plugin Mosquitto Dynamic Security de cap/thu hoi tai khoan MQTT khi dang chay.
`prepare_broker_v2.py` chuyen tu cau hinh file password/ACL cu va giu mat khau ESP32 hien tai.
Lan dau chuyen doi can dung broker truoc khi chay script. Setup tu goi phan chuan bi nay cho cai dat moi.
File `broker-v2.ready` ngan viec ghi de tai khoan/credential da doi tu API. Xem `../docs/BACKEND.md`.

Tai lieu: https://mosquitto.org/download/ ; https://eclipse.dev/paho/clients/python/docs/ ;
https://github.com/tzapu/WiFiManager ; https://pubsubclient.knolleary.net/api


Kiểm tra đường truyền mà không ghi dữ liệu mẫu:

```powershell
.\backend\.venv\Scripts\python.exe mqtt/check_telemetry.py --seconds 40
```

Bộ kiểm tra đếm từng bản tin thật trên broker (kể cả trạng thái không đổi), số bản tin sai và khoảng
trống lớn nhất. `Monitor.ps1` chỉ in thay đổi/định kỳ 60 giây nên có thể ít dòng dù heartbeat vẫn đều.
