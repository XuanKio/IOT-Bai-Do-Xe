import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.mqtt_receiver import MqttReceiver

parser = argparse.ArgumentParser()
parser.add_argument("--seconds", type=float, default=0)
args = parser.parse_args()
credentials = json.loads((ROOT / "mqtt/runtime/credentials.json").read_text())
connection = json.loads((ROOT / "mqtt/runtime/connection.json").read_text())
logging.basicConfig(level=logging.INFO, format="%(message)s")
receiver = MqttReceiver(lambda item, received_at: None, client_id="monitor-" + str(time.time_ns()),
                        username="receiver", password=credentials["receiver"], port=connection["port"])
receiver.start()
print("Cho ESP32 gui du lieu. Ctrl+C de thoat. MO PHONG la du lieu thu, khong phai cam bien.", flush=True)
try:
    start = time.monotonic()
    while not args.seconds or time.monotonic() - start < args.seconds:
        time.sleep(0.2)
except KeyboardInterrupt:
    pass
finally:
    receiver.stop()
