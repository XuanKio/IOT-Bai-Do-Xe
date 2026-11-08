"""Read-only broker probe: count every reading, including unchanged heartbeats."""
import argparse
import json
from pathlib import Path
import re
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.mqtt_receiver import parse_message


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=30, choices=range(1, 301), metavar="1..300")
    parser.add_argument("--device", default="esp32_01")
    args = parser.parse_args()
    credentials = json.loads((ROOT / "mqtt/runtime/credentials.json").read_text())
    connection = json.loads((ROOT / "mqtt/runtime/connection.json").read_text())
    topic = f"iot/{args.device}/lm393"
    # Validate the topic/device without opening any database or sending readings.
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}", args.device):
        parser.error("invalid device ID")
    lock = threading.Lock()
    started = time.monotonic()
    stats = {"received": 0, "invalid": 0, "retained": 0, "subscribed": False,
             "max_gap_s": 0.0, "first_seq": None, "last_seq": None, "firmware": None,
             "report_interval_ms": None, "boot_ids": []}
    last = [None]
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="telemetry-check-" + uuid.uuid4().hex[:12])
    client.username_pw_set("receiver", credentials["receiver"])

    def on_connect(c, userdata, flags, reason, properties):
        if not reason.is_failure:
            c.subscribe(topic, qos=1)

    def on_subscribe(c, userdata, mid, reasons, properties):
        with lock:
            stats["subscribed"] = bool(reasons) and all(not reason.is_failure for reason in reasons)

    def on_message(c, userdata, message):
        with lock:
            if message.retain:
                stats["retained"] += 1
                return
            try:
                item = parse_message(message.topic, message.payload)
            except ValueError:
                stats["invalid"] += 1
                return
            now = time.monotonic()
            stats["max_gap_s"] = max(stats["max_gap_s"], now - (last[0] or started))
            last[0] = now
            stats["received"] += 1
            if stats["first_seq"] is None:
                stats["first_seq"] = item.seq
            stats["last_seq"], stats["firmware"] = item.seq, item.firmware
            stats["report_interval_ms"] = item.report_interval_ms
            if item.boot_id not in stats["boot_ids"]:
                stats["boot_ids"].append(item.boot_id)

    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    client.connect("127.0.0.1", int(connection["port"]), keepalive=15)
    client.loop_start()
    stop = threading.Event()
    try:
        for elapsed in range(args.seconds):
            stop.wait(1)
            if (elapsed + 1) % 10 == 0:
                with lock:
                    age = round(time.monotonic() - last[0], 2) if last[0] else None
                    print(json.dumps({"elapsed_s": elapsed + 1, "received": stats["received"],
                                      "last_age_s": age}), flush=True)
    finally:
        client.disconnect()
        client.loop_stop()
    with lock:
        stats["max_gap_s"] = round(max(stats["max_gap_s"], time.monotonic() - (last[0] or started)), 2)
        print(json.dumps(stats, indent=2), flush=True)
        threshold = max(10, (stats["report_interval_ms"] or 1000) * 3 / 1000)
        return 0 if stats["received"] and stats["max_gap_s"] < threshold and not stats["invalid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
