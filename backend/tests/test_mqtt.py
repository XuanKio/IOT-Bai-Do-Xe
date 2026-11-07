import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from app.mqtt_receiver import MqttReceiver, parse_message, format_message


def payload(**changes):
    item = {"device_id": "esp32_01", "uptime_s": 10, "do": 0, "detected": True}
    item.update(changes)
    return json.dumps(item).encode()


@pytest.mark.parametrize("level,detected", [(0, True), (1, False)])
def test_both_sensor_levels(level, detected):
    item = parse_message("iot/esp32_01/lm393", payload(do=level, detected=detected))
    assert item.detected is detected


@pytest.mark.parametrize("topic,data", [
    ("iot/other/lm393", payload()),
    ("iot/simulator/lm393", payload()),
    ("iot/esp32_01/lm393", payload(detected=False)),
    ("iot/esp32_01/lm393", payload(do=2)),
    ("iot/esp32_01/lm393", payload(do=True)),
    ("iot/esp32_01/lm393", payload(uptime_s=-1)),
    ("iot/esp32_01/lm393", payload(uptime_s=2**80)),
    ("iot/esp32_01/lm393", payload(do2=0)),
    ("iot/esp32_01/lm393", payload(detected2=True)),
    ("iot/esp32_01/lm393", payload(do2=0, detected2=False)),
    ("iot/esp32_01/lm393", payload(do2=True, detected2=False)),
    ("iot/esp32_01/lm393", b"not-json"),
    ("iot/esp32_01/lm393", b"x" * 1025),
])
def test_invalid_readings_rejected(topic, data):
    with pytest.raises(ValueError):
        parse_message(topic, data)


def test_retained_readings_are_not_recorded_as_live():
    recorded = []
    receiver = MqttReceiver(lambda item, stamp: recorded.append(item), username="test", password="test")
    message = SimpleNamespace(topic="iot/esp32_01/lm393", payload=payload(), retain=True)
    receiver._on_message(None, None, message)
    assert not recorded
    message.retain = False
    receiver._on_message(None, None, message)
    assert len(recorded) == 1


def test_storage_error_does_not_kill_receiver():
    def fail(item, stamp):
        raise RuntimeError("Storage unavailable")
    receiver = MqttReceiver(fail, username="test", password="test")
    receiver._on_message(None, None, SimpleNamespace(
        topic="iot/esp32_01/lm393", payload=payload(), retain=False))


def test_console_logs_changes_and_checkpoints_instead_of_every_heartbeat(monkeypatch, caplog):
    from app import mqtt_receiver as module
    start = datetime.now(timezone.utc)
    stamps = iter([start, start + timedelta(seconds=1), start + timedelta(seconds=2), start + timedelta(seconds=63)])
    monkeypatch.setattr(module, "datetime", SimpleNamespace(now=lambda tz: next(stamps)))
    receiver = MqttReceiver(lambda item, stamp: True, username="test", password="test")
    with caplog.at_level(logging.INFO, logger="app.mqtt_receiver"):
        for level in (1, 1, 0, 0):
            receiver._on_message(None, None, SimpleNamespace(topic="iot/esp32_01/lm393",
                payload=payload(do=level, detected=level == 0), retain=False))
    assert len([r for r in caplog.records if r.name == "app.mqtt_receiver" and r.levelno == logging.INFO]) == 3


@pytest.mark.parametrize("level1,level2", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_two_sensors_are_independent(level1, level2):
    item = parse_message("iot/esp32_01/lm393", payload(
        do=level1, detected=level1 == 0, do2=level2, detected2=level2 == 0))
    assert item.detected == (level1 == 0)
    assert item.detected2 == (level2 == 0)


def gate_values(entrance=1, exit=1):
    return {"entrance": {"gpio": 32, "do": entrance, "detected": entrance == 0},
            "exit": {"gpio": 33, "do": exit, "detected": exit == 0}}


@pytest.mark.parametrize("entrance,exit", [(0, 0), (0, 1), (1, 0), (1, 1)])
def test_gate_presence_and_monitor_are_independent_of_parking(entrance, exit):
    item = parse_message("iot/esp32_01/lm393", payload(do2=1, detected2=False,
                         gate_sensors=gate_values(entrance, exit)))
    assert item.gate_sensors.entrance.detected == (entrance == 0)
    assert item.gate_sensors.exit.detected == (exit == 0)
    assert item.detected is True and item.detected2 is False
    text = format_message(item, datetime.now(timezone.utc))
    assert f"VAO(D32)={entrance}" in text and f"RA(D33)={exit}" in text


@pytest.mark.parametrize("change", [
    {"entrance": {"gpio": 32, "do": 0, "detected": False}},
    {"exit": {"gpio": 33, "do": True, "detected": False}},
    {"exit": {"gpio": 32, "do": 1, "detected": False}},
    {"exit": {"gpio": 33, "do": 2, "detected": False}},
    {"exit": {"gpio": 40, "do": 1, "detected": False}},
])
def test_invalid_gate_presence_is_rejected(change):
    with pytest.raises(ValueError):
        parse_message("iot/esp32_01/lm393", payload(gate_sensors={**gate_values(), **change}))


def test_gate_monitor_logs_presence_changes_without_parking_changes(caplog):
    receiver = MqttReceiver(lambda item, stamp: True, username="test", password="test")
    with caplog.at_level(logging.INFO, logger="app.mqtt_receiver"):
        for entrance, exit in [(1, 1), (0, 1), (0, 1), (0, 0)]:
            receiver._on_message(None, None, SimpleNamespace(topic="iot/esp32_01/lm393",
                payload=payload(gate_sensors=gate_values(entrance, exit)), retain=False))
    assert len([r for r in caplog.records if r.name == "app.mqtt_receiver"]) == 3


@pytest.mark.parametrize("enabled,stored,requested,expected", [
    (True, True, True, 1), (False, True, True, 0),
    (True, False, True, 0), (True, True, False, 0),
])
def test_delivery_ack_only_follows_server_acceptance(enabled, stored, requested, expected):
    sent = []
    receiver = MqttReceiver(lambda item, stamp: stored, username="test", password="test", ack_telemetry=enabled)
    receiver.publish_command = lambda device, body: sent.append((device, body))
    receiver._on_message(None, None, SimpleNamespace(topic="iot/esp32_01/lm393", retain=False,
        payload=payload(boot_id="11111111", seq=4, delivery_ack=requested)))
    assert len(sent) == expected
    if expected:
        assert sent == [("esp32_01", {"action": "telemetry_ack", "boot_id": "11111111", "seq": 4})]
