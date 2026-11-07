#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <esp_random.h>
#include <ESPmDNS.h>
#include "gate_sensor.h"
#include "gate_controller.h"
#include "mqtt_write.h"
#include "telemetry_delivery.h"
#include <lwip/sockets.h>
#include <errno.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#if __has_include("config.local.h")
#include "config.local.h"
#else
#error "Run mqtt/Setup.ps1 to generate config.local.h before compiling."
#endif

// O do 1: OUT/DO -> D27. O do 2: OUT/DO -> D26. Chi dung muc logic 3.3V.
// Cong vao: OUT/DO -> D32. Cong ra: OUT/DO -> D33. Co vat/xe = LOW.
// D4 la tin hieu HIGH, khong dung cap nguon cho module.
constexpr uint8_t SLOT1_PIN = 27;
constexpr uint8_t SLOT2_PIN = 26;
constexpr uint8_t ENTRANCE_SENSOR_PIN = 32;
constexpr uint8_t EXIT_SENSOR_PIN = 33;
constexpr uint8_t SERVO_PINS[2] = {18, 19};
// Calibrate these two positions for each arm before mounting the barrier.
constexpr uint8_t SERVO_CLOSED_DEGREES[2] = {0, 0};
constexpr uint8_t SERVO_OPEN_DEGREES[2] = {90, 90};
constexpr uint16_t SERVO_MIN_PULSE_US[2] = {500, 500};
constexpr uint16_t SERVO_MAX_PULSE_US[2] = {2500, 2500};
constexpr uint8_t ALWAYS_HIGH_PIN = 4;
constexpr uint32_t RECONNECT_INTERVAL_MS = 5000;
constexpr char FIRMWARE_VERSION[] = "esp32_core-0.4.3";
constexpr char BROKER_MDNS_HOST[] = "parkflow-iot";
constexpr uint32_t BROKER_LOOKUP_TIMEOUT_MS = 800;
char telemetryTopic[96], commandTopic[96], ackTopic[96], statusTopic[96];
char bootId[17], mqttClientId[96];
String offlineWill;
Preferences settings;
uint32_t reportIntervalMs = 1000;
uint32_t sampleSeq = 0;
TelemetryDelivery telemetryDelivery;
String cachedCommandIds[8], cachedAcks[8];
uint8_t nextAckSlot = 0;
GateSensor entranceSensor, exitSensor;
GateController gateControllers[2];
SemaphoreHandle_t gateMutex = nullptr;
bool gateReadingPending = false;
bool servoAttempted[2] = {false, false}, servoReady[2] = {false, false};
const char* GATE_NAMES[2] = {"entrance", "exit"};
const char* MODE_KEYS[2] = {"gate_in_auto", "gate_out_auto"};

bool writeServo(uint8_t index) {
  const uint8_t degrees = gateControllers[index].opened() ? SERVO_OPEN_DEGREES[index] : SERVO_CLOSED_DEGREES[index];
  const uint32_t pulseUs = SERVO_MIN_PULSE_US[index] + static_cast<uint32_t>(degrees) *
      (SERVO_MAX_PULSE_US[index] - SERVO_MIN_PULSE_US[index]) / 180;
  return ledcWrite(SERVO_PINS[index], pulseUs * 65535UL / 20000UL);
}

// A separate task keeps the 3-second timer running during MQTT/DNS reconnects.
void gateTask(void*) {
  for (;;) {
    if (xSemaphoreTake(gateMutex, portMAX_DELAY) == pdTRUE) {
      const uint32_t now = millis();
      const bool inChanged = entranceSensor.sample(digitalRead(ENTRANCE_SENSOR_PIN), now);
      const bool outChanged = exitSensor.sample(digitalRead(EXIT_SENSOR_PIN), now);
      if (inChanged || outChanged) gateReadingPending = true;
      GateSensor* sensors[2] = {&entranceSensor, &exitSensor};
      for (uint8_t i = 0; i < 2; i++) {
        if (!sensors[i]->ready()) continue;
        bool changed = gateControllers[i].update(sensors[i]->level() == LOW, now);
        if (!servoAttempted[i]) {
          servoAttempted[i] = true;
          servoReady[i] = ledcAttachChannel(SERVO_PINS[i], 50, 16, i);
          changed = true;
        }
        if (changed) {
          if (servoReady[i] && !writeServo(i)) servoReady[i] = false;
          gateReadingPending = true;
        }
      }
      xSemaphoreGive(gateMutex);
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// Apply TCP_NODELAY immediately after TCP connect, before MQTT CONNECT is sent.
class MqttNetworkClient : public WiFiClient {
 public:
  using WiFiClient::write;
  size_t write(const uint8_t* data, size_t size) override {
    if (fd() < 0) return 0;
    const size_t written = boundedMqttWrite(data, size, 1500,
      [this](const uint8_t* chunk, size_t length) -> int {
        const int result = ::send(fd(), chunk, length, MSG_DONTWAIT);
        if (result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR)) return 0;
        return result;
      }, []() -> uint32_t { return millis(); }, []() { vTaskDelay(pdMS_TO_TICKS(10)); });
    // A partial MQTT frame makes this TCP stream unusable for the next packet.
    if (written != size) stop();
    return written;
  }
  int connect(IPAddress ip, uint16_t port) override {
    const int connected = WiFiClient::connect(ip, port);
    if (connected) setNoDelay(true);
    return connected;
  }
  int connect(const char* host, uint16_t port) override {
    const int connected = WiFiClient::connect(host, port);
    if (connected) setNoDelay(true);
    return connected;
  }
};
MqttNetworkClient network;
PubSubClient mqtt(network);
WiFiManager wifiManager;
uint32_t lastReportMs = 0;
uint32_t lastReconnectMs = 0;
uint32_t reconnectDelayMs = RECONNECT_INTERVAL_MS;
uint32_t lastWifiAttemptMs = 0;
bool mqttTried = false;
bool wifiWasConnected = false;
bool mdnsReady = false;
IPAddress lastBrokerIP;
char mdnsHostname[32];

bool publishMessage(const char* topic, const char* payload, bool retained) {
  if (!mqtt.connected()) return false;
  const bool sent = mqtt.publish(topic, payload, retained);
  if (!sent) {
    network.stop();
    lastReconnectMs = millis();
    reconnectDelayMs = RECONNECT_INTERVAL_MS;
    xSemaphoreTake(gateMutex, portMAX_DELAY);
    gateReadingPending = true;
    xSemaphoreGive(gateMutex);
  }
  return sent;
}

void findBroker() {
  if (!mdnsReady) mdnsReady = MDNS.begin(mdnsHostname);
  IPAddress discovered;
  if (mdnsReady) discovered = MDNS.queryHost(BROKER_MDNS_HOST, BROKER_LOOKUP_TIMEOUT_MS);
  if (discovered != IPAddress()) {
    lastBrokerIP = discovered;
    mqtt.setServer(lastBrokerIP, MQTT_PORT);
    Serial.print("MQTT tim thay qua mDNS: ");
    Serial.println(lastBrokerIP);
  } else if (lastBrokerIP != IPAddress()) {
    mqtt.setServer(lastBrokerIP, MQTT_PORT);
    Serial.print("mDNS chua phan hoi; thu IP gan nhat: ");
    Serial.println(lastBrokerIP);
  } else {
    mqtt.setServer(MQTT_HOST, MQTT_PORT);
    Serial.print("mDNS chua phan hoi; thu IP cau hinh: ");
    Serial.println(MQTT_HOST);
  }
}

void handleCommand(char* topic, byte* payload, unsigned int length) {
  if (strcmp(topic, commandTopic) != 0 || length > 700) return;
  JsonDocument command;
  if (deserializeJson(command, payload, length)) return;
  const String id = command["command_id"] | "";
  const String action = command["action"] | "";
  const String targetBoot = command["boot_id"] | "";
  if (action == "telemetry_ack") {
    if (targetBoot == bootId && command["seq"].is<uint32_t>()) {
      telemetryDelivery.acknowledge(command["seq"].as<uint32_t>(), millis());
    }
    return;
  }
  if (id.length() != 32) return;
  for (size_t index = 0; index < id.length(); index++) {
    const char ch = id[index];
    if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) return;
  }
  for (uint8_t index = 0; index < 8; index++) {
    if (cachedCommandIds[index] == id) {
      publishMessage(ackTopic, cachedAcks[index].c_str(), false);
      return;
    }
  }
  bool success = false;
  const char* error = "Unsupported command";
  if (targetBoot != bootId || !command["uptime_deadline_s"].is<uint32_t>()) {
    error = "Command targets another boot or has no deadline";
  } else if (millis() / 1000 >= command["uptime_deadline_s"].as<uint32_t>()) {
    error = "Command expired";
  } else if (action == "ping") {
    success = true;
  } else if (action == "gate" || action == "gate_mode") {
    const String gate = command["arguments"]["gate"] | "";
    const int index = gate == "entrance" ? 0 : gate == "exit" ? 1 : -1;
    if (index < 0 || !command["arguments"]["revision"].is<uint32_t>()) {
      error = "Invalid gate or revision";
    } else {
      xSemaphoreTake(gateMutex, portMAX_DELAY);
      GateSensor& sensor = index == 0 ? entranceSensor : exitSensor;
      GateController& controller = gateControllers[index];
      const uint32_t revision = command["arguments"]["revision"].as<uint32_t>();
      if (!sensor.ready() || !servoReady[index]) error = "Gate PWM is not ready";
      else if (revision <= controller.revision()) error = "Stale gate revision";
      else if (action == "gate_mode") {
        const String mode = command["arguments"]["mode"] | "";
        if (mode != "auto" && mode != "manual") error = "Invalid gate mode";
        else if (controller.automatic() != (mode == "auto") && settings.putBool(MODE_KEYS[index], mode == "auto") != 1)
          error = "Could not save gate mode";
        else success = controller.setMode(mode == "auto", revision, sensor.level() == LOW, millis());
      } else {
        const String target = command["arguments"]["target"] | "";
        if (target != "open" && target != "closed") error = "Invalid gate target";
        else if (controller.automatic()) error = "Select manual mode first";
        else success = controller.setTarget(target == "open", revision);
      }
      if (success && !writeServo(index)) { servoReady[index] = false; success = false; error = "Gate PWM write failed"; }
      if (success) gateReadingPending = true;
      xSemaphoreGive(gateMutex);
    }
  } else if (action == "configure") {
    if (!command["arguments"]["report_interval_ms"].is<uint32_t>()) {
      error = "Invalid report interval";
    } else {
      const uint32_t requested = command["arguments"]["report_interval_ms"].as<uint32_t>();
      if (requested < 500 || requested > 10000) {
        error = "Report interval must be 500..10000 ms";
      } else if (requested == reportIntervalMs || settings.putUInt("report_ms", requested) == sizeof(uint32_t)) {
        reportIntervalMs = requested;
        success = true;
      } else {
        error = "Could not save configuration";
      }
    }
  }
  JsonDocument ack;
  ack["device_id"] = MQTT_USERNAME;
  ack["command_id"] = id;
  ack["boot_id"] = bootId;
  ack["status"] = success ? "succeeded" : "failed";
  ack["result"]["report_interval_ms"] = reportIntervalMs;
  ack["result"]["uptime_s"] = millis() / 1000;
  if (success && (action == "gate" || action == "gate_mode")) {
    const String gate = command["arguments"]["gate"];
    const uint8_t index = gate == "entrance" ? 0 : 1;
    xSemaphoreTake(gateMutex, portMAX_DELAY);
    ack["result"]["gate"] = gate;
    ack["result"]["revision"] = gateControllers[index].revision();
    ack["result"]["mode"] = gateControllers[index].automatic() ? "auto" : "manual";
    ack["result"]["target"] = gateControllers[index].opened() ? "open" : "closed";
    ack["result"]["pwm_ready"] = servoReady[index];
    xSemaphoreGive(gateMutex);
  }
  if (!success) ack["error"] = error;
  String encoded;
  serializeJson(ack, encoded);
  cachedCommandIds[nextAckSlot] = id;
  cachedAcks[nextAckSlot] = encoded;
  nextAckSlot = (nextAckSlot + 1) % 8;
  publishMessage(ackTopic, encoded.c_str(), false);
  Serial.print("Lenh ");
  Serial.print(action);
  Serial.print(success ? " OK | Chu ky gui: " : " THAT BAI | Chu ky gui: ");
  Serial.print(reportIntervalMs);
  Serial.println(" ms");
}

void startWifiPortal() {
  Serial.print("Cau hinh Wi-Fi: ket noi mang ");
  Serial.println(SETUP_AP_NAME);
  Serial.print("Mat khau mang cau hinh: ");
  Serial.println(SETUP_AP_PASSWORD);
  Serial.println("Mo http://192.168.4.1 va chon Wi-Fi 2.4 GHz cung LAN voi may tinh.");
  wifiManager.startConfigPortal(SETUP_AP_NAME, SETUP_AP_PASSWORD);
}

void setup() {
  pinMode(ALWAYS_HIGH_PIN, OUTPUT);
  digitalWrite(ALWAYS_HIGH_PIN, HIGH);
  pinMode(SLOT1_PIN, INPUT_PULLUP);
  pinMode(SLOT2_PIN, INPUT_PULLUP);
  pinMode(ENTRANCE_SENSOR_PIN, INPUT_PULLUP);
  pinMode(EXIT_SENSOR_PIN, INPUT_PULLUP);
  entranceSensor.begin(digitalRead(ENTRANCE_SENSOR_PIN), millis());
  exitSensor.begin(digitalRead(EXIT_SENSOR_PIN), millis());
  Serial.begin(115200);
  Serial.println("Cam bien: P1=D27, P2=D26, CONG VAO=D32, CONG RA=D33. LOW=CO XE.");

  settings.begin("iot-settings", false);
  for (uint8_t i = 0; i < 2; i++) gateControllers[i].restoreMode(settings.getBool(MODE_KEYS[i], true));
  gateMutex = xSemaphoreCreateMutex();
  if (!gateMutex || xTaskCreate(gateTask, "gate-control", 4096, nullptr, 2, nullptr) != pdPASS) {
    Serial.println("Gate task initialization failed");
    for (;;) delay(1000);
  }
  reportIntervalMs = settings.getUInt("report_ms", 1000);
  if (reportIntervalMs < 500 || reportIntervalMs > 10000) reportIntervalMs = 1000;
  snprintf(bootId, sizeof(bootId), "%08lx%08lx", static_cast<unsigned long>(esp_random()), static_cast<unsigned long>(esp_random()));
  snprintf(mqttClientId, sizeof(mqttClientId), "%s-%06lx", MQTT_USERNAME,
           static_cast<unsigned long>(ESP.getEfuseMac() & 0xFFFFFF));
  snprintf(mdnsHostname, sizeof(mdnsHostname), "parkflow-%06lx",
           static_cast<unsigned long>(ESP.getEfuseMac() & 0xFFFFFF));
  snprintf(telemetryTopic, sizeof(telemetryTopic), "iot/%s/lm393", MQTT_USERNAME);
  snprintf(commandTopic, sizeof(commandTopic), "iot/%s/commands", MQTT_USERNAME);
  snprintf(ackTopic, sizeof(ackTopic), "iot/%s/ack", MQTT_USERNAME);
  snprintf(statusTopic, sizeof(statusTopic), "iot/%s/status", MQTT_USERNAME);
  JsonDocument will;
  will["device_id"] = MQTT_USERNAME;
  will["state"] = "offline";
  will["boot_id"] = bootId;
  serializeJson(will, offlineWill);

  network.setConnectionTimeout(4000);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setKeepAlive(15);
  mqtt.setSocketTimeout(8);
  mqtt.setBufferSize(1536);
  mqtt.setCallback(handleCommand);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // Keep manual commands responsive on power-saving APs.
  WiFi.setAutoReconnect(true);
  wifiManager.setDebugOutput(false);
  wifiManager.setConfigPortalBlocking(false);
  wifiManager.setConnectTimeout(10);
  wifiManager.setConfigPortalTimeout(0);
  wifiManager.setHostname("esp32-iot-01");
  if (!wifiManager.getWiFiIsSaved()) {
    startWifiPortal();
  } else {
    WiFi.begin();
  }
  Serial.println("Serial 115200. Go w va Enter de mo lai trang cau hinh Wi-Fi.");
}

void loop() {
  wifiManager.process();
  if (Serial.available() && Serial.read() == 'w') startWifiPortal();

  uint32_t nowMs = millis();
  const bool wifiConnected = WiFi.status() == WL_CONNECTED;
  if (wifiConnected && !wifiWasConnected) {
    Serial.print("Wi-Fi OK | IP ESP32: ");
    Serial.println(WiFi.localIP());
    Serial.print("Wi-Fi MAC: ");
    Serial.println(WiFi.macAddress());
    Serial.println("MQTT broker: parkflow-iot.local (tu tim IP)");
    mqttTried = false;
  }
  if (!wifiConnected && wifiWasConnected) {
    mqtt.disconnect();
    MDNS.end();
    mdnsReady = false;
    lastBrokerIP = IPAddress();
  }
  wifiWasConnected = wifiConnected;

  if (!wifiConnected && !wifiManager.getConfigPortalActive() &&
      nowMs - lastWifiAttemptMs >= 15000) {
    lastWifiAttemptMs = nowMs;
    WiFi.reconnect();
  }
  if (wifiConnected && !mqtt.connected() &&
      (!mqttTried || nowMs - lastReconnectMs >= reconnectDelayMs)) {
    mqttTried = true;
    // Drop the previous socket before creating another MQTT connection.
    network.stop();
    findBroker();
    if (mqtt.connect(mqttClientId, MQTT_USERNAME, MQTT_PASSWORD, statusTopic, 1, true, offlineWill.c_str(), true)) {
      JsonDocument online;
      online["device_id"] = MQTT_USERNAME;
      online["state"] = "online";
      online["boot_id"] = bootId;
      String onlinePayload;
      serializeJson(online, onlinePayload);
      if (mqtt.subscribe(commandTopic, 1) && publishMessage(statusTopic, onlinePayload.c_str(), true)) {
        xSemaphoreTake(gateMutex, portMAX_DELAY);
        gateReadingPending = true;
        xSemaphoreGive(gateMutex);
        Serial.println("MQTT OK");
        reconnectDelayMs = RECONNECT_INTERVAL_MS;
        telemetryDelivery.reset(millis());
      } else {
        network.stop();
        reconnectDelayMs = min(reconnectDelayMs * 2, uint32_t(30000));
        Serial.println("MQTT subscribe/status failed; reconnecting later");
      }
    } else {
      Serial.print("MQTT chua ket noi | ma loi: ");
      Serial.println(mqtt.state());
      network.stop();
      reconnectDelayMs = min(reconnectDelayMs * 2, uint32_t(30000));
    }
    // Backoff begins after the attempt, including its TCP/MQTT wait time.
    lastReconnectMs = millis();
  }
  if (wifiConnected && mqtt.connected()) mqtt.loop();
  if (mqtt.connected() && telemetryDelivery.overdue(millis(), reportIntervalMs)) {
    Serial.println("MQTT delivery timeout; resetting TCP connection");
    network.stop();
    mqttTried = false;  // The delivery watchdog gets one immediate retry.
  }

  nowMs = millis();
  xSemaphoreTake(gateMutex, portMAX_DELAY);
  const bool gateSnapshotReady = entranceSensor.ready() && exitSensor.ready();
  const bool gatesDirty = gateReadingPending;
  xSemaphoreGive(gateMutex);
  if (nowMs - lastReportMs >= reportIntervalMs ||
      (gatesDirty && gateSnapshotReady && wifiConnected && mqtt.connected() &&
       nowMs - lastReportMs >= 100)) {
    lastReportMs = nowMs;
    const int level1 = digitalRead(SLOT1_PIN);
    const int level2 = digitalRead(SLOT2_PIN);
    char payload[1280];
    JsonDocument reading;
    reading["device_id"] = MQTT_USERNAME;
    reading["uptime_s"] = nowMs / 1000;
    reading["do"] = level1;
    reading["detected"] = level1 == LOW;
    reading["do2"] = level2;
    reading["detected2"] = level2 == LOW;
    reading["boot_id"] = bootId;
    reading["seq"] = sampleSeq++;
    reading["firmware"] = FIRMWARE_VERSION;
    reading["hardware"] = ESP.getChipModel();
    reading["report_interval_ms"] = reportIntervalMs;
    reading["delivery_ack"] = true;
    xSemaphoreTake(gateMutex, portMAX_DELAY);
    if (gateSnapshotReady) {
      reading["gate_sensors"]["entrance"]["gpio"] = ENTRANCE_SENSOR_PIN;
      reading["gate_sensors"]["entrance"]["do"] = entranceSensor.level();
      reading["gate_sensors"]["entrance"]["detected"] = entranceSensor.level() == LOW;
      reading["gate_sensors"]["exit"]["gpio"] = EXIT_SENSOR_PIN;
      reading["gate_sensors"]["exit"]["do"] = exitSensor.level();
      reading["gate_sensors"]["exit"]["detected"] = exitSensor.level() == LOW;
      for (uint8_t i = 0; i < 2; i++) {
        auto gate = reading["gate_control"][GATE_NAMES[i]].to<JsonObject>();
        gate["mode"] = gateControllers[i].automatic() ? "auto" : "manual";
        gate["target"] = gateControllers[i].opened() ? "open" : "closed";
        gate["servo_gpio"] = SERVO_PINS[i];
        gate["pwm_ready"] = servoReady[i];
        gate["revision"] = gateControllers[i].revision();
        gate["close_remaining_ms"] = gateControllers[i].remaining(millis());
      }
    }
    gateReadingPending = false;
    xSemaphoreGive(gateMutex);
    const bool fitsPayload = measureJson(reading) < sizeof(payload);
    if (fitsPayload) serializeJson(reading, payload, sizeof(payload));
    // Khong retain: tranh coi gia tri cu la phep do moi sau khi ket noi lai.
    const uint32_t txStartedMs = millis();
    const bool sent = fitsPayload && wifiConnected && publishMessage(telemetryTopic, payload, false);
    const uint32_t txElapsedMs = millis() - txStartedMs;
    if (sent) telemetryDelivery.sent(sampleSeq - 1);
    if (!sent) {
      xSemaphoreTake(gateMutex, portMAX_DELAY);
      gateReadingPending = true;
      xSemaphoreGive(gateMutex);
    }
    Serial.print("Thoi gian: ");
    Serial.print(nowMs / 1000);
    Serial.print(" s | P1(D27)=");
    Serial.print(level1);
    Serial.print(level1 == LOW ? " CO XE" : " TRONG");
    Serial.print(" | P2(D26)=");
    Serial.print(level2);
    Serial.print(level2 == LOW ? " CO XE" : " TRONG");
    xSemaphoreTake(gateMutex, portMAX_DELAY);
    Serial.print(" | VAO(D32)=");
    if (entranceSensor.ready()) {
      Serial.print(entranceSensor.level());
      Serial.print(entranceSensor.level() == LOW ? " CO XE" : " TRONG");
    } else Serial.print("DANG DOC");
    Serial.print(" | RA(D33)=");
    if (exitSensor.ready()) {
      Serial.print(exitSensor.level());
      Serial.print(exitSensor.level() == LOW ? " CO XE" : " TRONG");
    } else Serial.print("DANG DOC");
    xSemaphoreGive(gateMutex);
    Serial.print(wifiConnected ? " | Wi-Fi=OK" : " | Wi-Fi=CHO");
    Serial.print(" | RSSI=");
    Serial.print(WiFi.RSSI());
    Serial.print(" | MQTT_STATE=");
    Serial.print(mqtt.state());
    Serial.print(" | TX_MS=");
    Serial.print(txElapsedMs);
    Serial.print(" | ACK_AGE_MS=");
    Serial.print(telemetryDelivery.age(millis()));
    Serial.println(sent ? " | MQTT=DA GUI" : " | MQTT=CHUA GUI");
  }
  delay(1);
}
