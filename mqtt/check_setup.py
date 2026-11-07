"""Verify the running broker, authentication, ACL, and backend storage."""
import json
import threading
import time
from pathlib import Path

import httpx
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
credentials = json.loads((ROOT / "mqtt/runtime/credentials.json").read_text())
connection = json.loads((ROOT / "mqtt/runtime/connection.json").read_text())


def connect_client(username=None, password=None):
    event = threading.Event()
    state = {}
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                         client_id="check-" + str(time.time_ns()), protocol=mqtt.MQTTv5)
    if username:
        client.username_pw_set(username, password)
    def on_connect(client, userdata, flags, reason_code, properties):
        state["accepted"] = not reason_code.is_failure
        event.set()
    client.on_connect = on_connect
    client.connect("127.0.0.1", connection["port"], 10)
    client.loop_start()
    if not event.wait(5):
        client.disconnect()
        client.loop_stop()
        raise RuntimeError("Connection check timed out")
    return client, state["accepted"]


def close(client):
    client.disconnect()
    client.loop_stop()


def main():
    for username, password, expected in [(None, None, False), ("esp32_01", "incorrect", False),
                                         ("esp32_01", credentials["esp32_01"], True)]:
        client, accepted = connect_client(username, password)
        close(client)
        assert accepted is expected, "Authentication check failed"
    print("PASS: anonymous/wrong passwords rejected; ESP32 credentials accepted")

    client, accepted = connect_client("simulator", credentials["simulator"])
    assert accepted
    event = threading.Event()
    results = []
    def on_publish(client, userdata, mid, reason_code, properties):
        results.append(reason_code.is_failure)
        event.set()
    client.on_publish = on_publish
    try:
        client.publish("iot/esp32_01/lm393", "{}", qos=1)
        assert event.wait(5) and results.pop(), "Simulator could publish to the real ESP32 topic"
        print("PASS: ACL prevents simulator publishing as real ESP32")

        with httpx.Client(base_url="http://127.0.0.1:8000", timeout=5) as api:
            assert api.get("/health").json()["mqtt_subscribed"]
            response = api.post("/auth/login", json={"username": "mqtt_admin", "password": credentials["admin_password"]})
            response.raise_for_status()
            api.headers["Authorization"] = "Bearer " + response.json()["access_token"]
            simulated_before = api.get("/telemetry/latest?device_id=simulator").json()
            for level in (0, 1):
                event.clear()
                payload = {"device_id": "simulator", "uptime_s": 100 + level,
                           "do": level, "detected": level == 0,
                           "do2": 1 - level, "detected2": level == 1}
                client.publish("iot/simulator/lm393", json.dumps(payload), qos=1)
                assert event.wait(5) and not results.pop(), "Simulator publish failed"
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    received = api.get("/telemetry/latest?device_id=simulator").json()
                    if (received and received["id"] != (simulated_before or {}).get("id")
                            and received["uptime_s"] == 100 + level):
                        break
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Backend did not store the published MQTT reading")
                assert received["do"] == level and received["detected"] == (level == 0)
                assert [(slot["name"], slot["do"]) for slot in received["slots"]] == [("P1", level), ("P2", 1 - level)]
                assert received["fresh"] and received["simulated"]
                simulated_before = received
            real_after = api.get("/telemetry/latest").json()
            assert real_after is None or (real_after["device_id"] == "esp32_01" and not real_after["simulated"])
            assert api.get("/telemetry?device_id=simulator").json()
        print("PASS: MQTT -> backend -> database -> authenticated API for LOW and HIGH")
        print("PASS: simulation stays separate from real ESP32 readings")
    finally:
        close(client)


if __name__ == "__main__":
    main()
