"""Update the local broker address without regenerating credentials or access rules."""
import argparse
import ipaddress
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def prepare_roaming_listener(root: Path) -> bool:
    runtime = root / "mqtt" / "runtime"
    connection = json.loads((runtime / "connection.json").read_text(encoding="utf-8"))
    port, host = connection["port"], connection["host"]
    path = runtime / "mosquitto.conf"
    config = path.read_text(encoding="utf-8")
    if re.search(rf"(?m)^listener {port} 0\.0\.0\.0$", config):
        return False
    pattern = rf"(?m)^listener[ \t]+{port}[ \t]+(?:127\.0\.0\.1|{re.escape(host)})[ \t]*\n?"
    listeners = re.findall(pattern, config)
    if len(listeners) != 2 or host == "127.0.0.1":
        raise ValueError("Expected the project's loopback and LAN listeners before enabling IP roaming")
    config = re.sub(pattern, "", config)
    path.write_text(f"listener {port} 0.0.0.0\n" + config, encoding="utf-8")
    print("MQTT listener now accepts IPv4 address changes; authentication and access rules preserved.")
    return True


def sync_network(root: Path, host: str) -> bool:
    address = ipaddress.IPv4Address(host)
    if address.is_unspecified or address.is_multicast or address.is_loopback or address.is_link_local:
        raise ValueError("Broker address must be a LAN IPv4 address")
    runtime = root / "mqtt" / "runtime"
    connection_path = runtime / "connection.json"
    connection = json.loads(connection_path.read_text(encoding="utf-8"))
    old_host, port = connection["host"], connection["port"]
    if old_host == host:
        return False

    config_path = runtime / "mosquitto.conf"
    config = config_path.read_text(encoding="utf-8")
    config, count = re.subn(
        rf"(?m)^listener[ \t]+{port}[ \t]+{re.escape(old_host)}[ \t]*$",
        f"listener {port} {host}", config,
    )
    roaming = re.search(rf"(?m)^listener {port} 0\.0\.0\.0$", config)
    if count != 1 and not (count == 0 and roaming):
        raise ValueError("Expected one LAN listener in mqtt/runtime/mosquitto.conf; check it before retrying")
    updates = {config_path: config}
    header_path = root / "esp32_core" / "config.local.h"
    if header_path.exists():
        header = header_path.read_text(encoding="utf-8")
        updates[header_path] = re.sub(
            r'(constexpr char MQTT_HOST\[\]\s*=\s*")[^"]*(";)',
            lambda match: match[1] + host + match[2], header,
        )
    info_path = runtime / "THONG_TIN_DANG_NHAP.txt"
    if info_path.exists():
        info = info_path.read_text(encoding="utf-8")
        updates[info_path] = re.sub(r"(?m)^Broker: .*$", f"Broker: {host}:{port}", info)
    connection["host"] = host
    updates[connection_path] = json.dumps(connection) + "\n"
    for path, content in updates.items():
        path.write_text(content, encoding="utf-8")
    print(f"MQTT computer IP changed: {old_host} -> {host}:{port}")
    print("ESP32 firmware 0.2.1+ finds parkflow-iot.local automatically while the backend is running.")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--roaming-listener", action="store_true")
    args = parser.parse_args()
    if not args.host and not args.roaming_listener:
        parser.error("Specify --host or --roaming-listener")
    if args.host:
        sync_network(ROOT, args.host)
    if args.roaming_listener:
        prepare_roaming_listener(ROOT)
