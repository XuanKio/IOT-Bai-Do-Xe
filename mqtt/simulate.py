"""Test the transport using a separate simulator identity/topic."""
import argparse
import json
import time
from pathlib import Path
import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--count", type=int, default=4)
args = parser.parse_args()
credentials = json.loads((ROOT / "mqtt/runtime/credentials.json").read_text())
connection = json.loads((ROOT / "mqtt/runtime/connection.json").read_text())
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="simulator-" + str(time.time_ns()))
client.username_pw_set("simulator", credentials["simulator"])
client.connect("127.0.0.1", connection["port"], 30)
client.loop_start()
try:
    deadline = time.monotonic() + 5
    while not client.is_connected():
        if time.monotonic() > deadline:
            raise RuntimeError("MQTT simulator could not connect")
        time.sleep(0.05)
    for index in range(args.count):
        level = index % 2
        level2 = (index // 2) % 2
        payload = {"device_id": "simulator", "uptime_s": index + 1, "do": level,
                   "detected": level == 0, "do2": level2, "detected2": level2 == 0}
        result = client.publish("iot/simulator/lm393", json.dumps(payload), qos=1, retain=False)
        result.wait_for_publish(timeout=5)
        if not result.is_published():
            raise RuntimeError("MQTT publish timeout")
        print("MO PHONG:", json.dumps(payload), flush=True)
        time.sleep(1)
finally:
    client.disconnect()
    client.loop_stop()
