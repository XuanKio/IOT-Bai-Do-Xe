"""MQTT input shared by the backend and the terminal monitor."""
import logging
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Literal

import paho.mqtt.client as mqtt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

logger = logging.getLogger(__name__)
BANGKOK = timezone(timedelta(hours=7))
TOPIC_PATTERN = re.compile(r"iot/([a-zA-Z0-9_][a-zA-Z0-9_-]{0,63})/lm393")


class GateSensorReading(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    gpio: int = Field(ge=0, le=39)
    do: int = Field(ge=0, le=1)
    detected: bool

    @model_validator(mode="after")
    def check_level(self):
        if self.detected != (self.do == 0):
            raise ValueError("gate detected must equal (do == 0)")
        return self


class GateSensors(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    entrance: GateSensorReading
    exit: GateSensorReading

    @model_validator(mode="after")
    def check_pins(self):
        if self.entrance.gpio == self.exit.gpio:
            raise ValueError("entrance and exit must use different GPIOs")
        return self


class GateControlState(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    mode: Literal["auto", "manual"]
    target: Literal["open", "closed"]
    servo_gpio: int = Field(ge=0, le=33)
    pwm_ready: bool
    revision: int = Field(ge=0, le=0xFFFFFFFF)
    close_remaining_ms: int = Field(ge=0, le=3000)

    @model_validator(mode="after")
    def check_countdown(self):
        if self.close_remaining_ms and (self.mode != "auto" or self.target != "open"):
            raise ValueError("only an automatic open gate can have a close countdown")
        return self


class GateControl(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    entrance: GateControlState
    exit: GateControlState

    @model_validator(mode="after")
    def check_pins(self):
        if self.entrance.servo_gpio == self.exit.servo_gpio:
            raise ValueError("servos must use different GPIOs")
        return self


class TelemetryMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")
    uptime_s: int = Field(ge=0, le=0xFFFFFFFF)
    do: int = Field(ge=0, le=1)
    detected: bool
    # Existing do/detected fields refer to P1 (D27). P2 is D26.
    do2: int | None = Field(default=None, ge=0, le=1)
    detected2: bool | None = None
    gate_sensors: GateSensors | None = None
    gate_control: GateControl | None = None
    boot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,32}$")
    seq: int | None = Field(default=None, ge=0, le=0xFFFFFFFF)
    firmware: str | None = Field(default=None, max_length=64)
    hardware: str | None = Field(default=None, max_length=64)
    report_interval_ms: int | None = Field(default=None, ge=500, le=10000)
    delivery_ack: bool = False

    @model_validator(mode="after")
    def check_level(self):
        if self.detected != (self.do == 0):
            raise ValueError("detected must equal (do == 0)")
        if (self.do2 is None) != (self.detected2 is None):
            raise ValueError("P2 level and detection must both be provided")
        if self.do2 is not None and self.detected2 != (self.do2 == 0):
            raise ValueError("detected2 must equal (do2 == 0)")
        if (self.boot_id is None) != (self.seq is None):
            raise ValueError("boot_id and seq must both be provided")
        return self


class AckMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    device_id: str = Field(min_length=1, max_length=64)
    command_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    boot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,32}$")
    status: Literal["succeeded", "failed"]
    result: dict = Field(default_factory=dict)
    error: str | None = Field(default=None, max_length=200)


class StatusMessage(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    device_id: str = Field(min_length=1, max_length=64)
    state: Literal["online", "offline"]
    boot_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{8,32}$")


def parse_message(topic: str, payload: bytes) -> TelemetryMessage:
    match = TOPIC_PATTERN.fullmatch(topic)
    if not match or len(payload) > 2048:
        raise ValueError("Invalid topic or oversized payload")
    item = TelemetryMessage.model_validate_json(payload)
    if item.device_id != match.group(1):
        raise ValueError("Device ID does not match topic")
    return item


def format_message(item: TelemetryMessage, received_at: datetime) -> str:
    kind = "MO PHONG" if item.device_id == "simulator" else "ESP32"
    result1 = "CO XE" if item.detected else "TRONG"
    result2 = "CHUA CO DU LIEU" if item.do2 is None else ("CO XE" if item.detected2 else "TRONG")
    stamp = received_at.astimezone(BANGKOK).strftime("%Y-%m-%d %H:%M:%S")
    gates = ""
    if item.gate_sensors:
        for name, sensor in (("VAO", item.gate_sensors.entrance), ("RA", item.gate_sensors.exit)):
            gates += f" | {name}(D{sensor.gpio})={sensor.do} {'CO XE' if sensor.detected else 'TRONG'}"
    return (f"[{stamp} +07] {kind} | uptime={item.uptime_s}s | P1(D27)={item.do} {result1}"
            f" | P2(D26)={item.do2 if item.do2 is not None else '?'} {result2}{gates}")


class MqttReceiver:
    def __init__(self, on_reading: Callable, *, client_id="iot-backend", host=None,
                 port=None, username=None, password=None, on_ack=None, on_status=None,
                 ack_telemetry=False):
        self.on_reading = on_reading
        self.on_ack, self.on_status = on_ack, on_status
        self.ack_telemetry = ack_telemetry
        self.connected = False
        self.subscribed = False
        self._telemetry_log = {}
        self.host = host or os.getenv("MQTT_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("MQTT_PORT", "1883"))
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        self.client.username_pw_set(username or os.environ["MQTT_USERNAME"],
                                    password or os.environ["MQTT_PASSWORD"])
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_subscribe = self._on_subscribe
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=15)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self.connected = not reason_code.is_failure
        self.subscribed = False
        if self.connected:
            topics = [("iot/+/lm393", 1)]
            if self.on_ack:
                topics.append(("iot/+/ack", 1))
            if self.on_status:
                topics.append(("iot/+/status", 1))
            client.subscribe(topics)
        else:
            logger.warning("MQTT connection refused: %s", reason_code)

    def _on_subscribe(self, client, userdata, mid, reason_codes, properties):
        self.subscribed = bool(reason_codes) and all(not code.is_failure for code in reason_codes)
        if self.subscribed:
            logger.info("MQTT ready: subscribed to iot/+/lm393")
        else:
            logger.error("MQTT subscription refused")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = self.subscribed = False

    def _on_message(self, client, userdata, message):
        # Old retained readings must not appear as a fresh physical measurement.
        if message.retain:
            return
        received_at = datetime.now(timezone.utc)
        if not message.topic.endswith("/lm393"):
            try:
                if len(message.payload) > 2048 or not re.fullmatch(
                        r"iot/[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}/(ack|status)", message.topic):
                    raise ValueError("Invalid control topic")
                model, callback = (AckMessage, self.on_ack) if message.topic.endswith("/ack") else (StatusMessage, self.on_status)
                item = model.model_validate_json(message.payload)
                if item.device_id != message.topic.split("/")[1]:
                    raise ValueError("Device mismatch")
                if callback:
                    callback(item, received_at)
            except Exception:
                logger.warning("Rejected invalid control message on %s", message.topic)
            return
        try:
            item = parse_message(message.topic, message.payload)
        except (ValueError, ValidationError):
            logger.warning("Rejected invalid MQTT reading on %s", message.topic)
            return
        try:
            stored = self.on_reading(item, received_at)
        except Exception:
            logger.exception("Could not store MQTT reading")
            return
        if stored is not False:
            if self.ack_telemetry and item.delivery_ack and item.boot_id is not None:
                self.publish_command(item.device_id, {"action": "telemetry_ack",
                    "boot_id": item.boot_id, "seq": item.seq})
            gates = item.gate_sensors.model_dump_json() if item.gate_sensors else None
            controls = item.gate_control.model_dump_json() if item.gate_control else None
            levels = (item.do, item.do2, item.boot_id, gates, controls)
            previous = self._telemetry_log.get(item.device_id)
            if previous is None or previous[0] != levels or (received_at - previous[1]).total_seconds() >= 60:
                logger.info(format_message(item, received_at))
                self._telemetry_log[item.device_id] = (levels, received_at)

    def publish_command(self, code, payload):
        if not self.connected or not self.subscribed:
            return False
        result = self.client.publish(f"iot/{code}/commands", json.dumps(payload), qos=1, retain=False)
        return result.rc == mqtt.MQTT_ERR_SUCCESS

    def start(self):
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def stop(self):
        self.client.disconnect()
        self.client.loop_stop()
        self.connected = self.subscribed = False
