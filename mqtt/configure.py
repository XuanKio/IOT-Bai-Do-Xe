"""Generate local credentials/configuration. Never prints passwords."""
import argparse
import json
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "mqtt" / "runtime"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=1884)
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    credentials_path = RUNTIME / "credentials.json"
    first_run = not credentials_path.exists()
    if first_run:
        credentials = {name: secrets.token_hex(18) for name in ("esp32_01", "receiver", "simulator")}
        credentials.update(ap_password=secrets.token_hex(6), jwt_secret=secrets.token_hex(48),
                           admin_password=secrets.token_urlsafe(18))
        credentials_path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    else:
        credentials = json.loads(credentials_path.read_text(encoding="utf-8"))

    executable = ROOT / ".tools" / "mosquitto" / "mosquitto_passwd.exe"
    password_file = RUNTIME / "passwords"
    if first_run or not password_file.exists():
        for index, name in enumerate(("esp32_01", "receiver", "simulator")):
            command = [str(executable), "-b"]
            if index == 0:
                command.append("-c")
            command.extend([str(password_file), name, credentials[name]])
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError("mosquitto_passwd failed; check the local Mosquitto installation")

    (RUNTIME / "acl").write_text(
        "user esp32_01\ntopic write iot/esp32_01/lm393\n\n"
        "user receiver\ntopic read iot/+/lm393\n\n"
        "user simulator\ntopic write iot/simulator/lm393\n", encoding="utf-8")
    config = (
        f"listener {args.port} 0.0.0.0\n"
        "allow_anonymous false\n"
        f"password_file {password_file.as_posix()}\n"
        f"acl_file {(RUNTIME / 'acl').as_posix()}\n"
        "persistence false\nlog_dest stdout\nlog_type error\nlog_type warning\nlog_type notice\n"
    )
    (RUNTIME / "mosquitto.conf").write_text(config, encoding="utf-8")
    header = (
        '#pragma once\n// Generated locally; do not share this file. MQTT_HOST is the fallback if mDNS is unavailable.\n'
        f'constexpr char MQTT_HOST[] = "{args.host}";\n'
        f'constexpr uint16_t MQTT_PORT = {args.port};\n'
        'constexpr char MQTT_USERNAME[] = "esp32_01";\n'
        f'constexpr char MQTT_PASSWORD[] = "{credentials["esp32_01"]}";\n'
        'constexpr char SETUP_AP_NAME[] = "ESP32-IOT-Setup";\n'
        f'constexpr char SETUP_AP_PASSWORD[] = "{credentials["ap_password"]}";\n'
    )
    (ROOT / "esp32_core" / "config.local.h").write_text(header, encoding="utf-8")
    (RUNTIME / "backend.env").write_text(
        f"MQTT_ENABLED=1\nMQTT_HOST=127.0.0.1\nMQTT_PORT={args.port}\nMQTT_USERNAME=receiver\n"
        f"MQTT_PASSWORD={credentials['receiver']}\nJWT_SECRET={credentials['jwt_secret']}\n"
        f"DATABASE_URL=sqlite:///{(ROOT / 'backend' / 'parking.db').as_posix()}\n", encoding="utf-8")
    (RUNTIME / "connection.json").write_text(json.dumps({"host": args.host, "port": args.port}), encoding="utf-8")
    (RUNTIME / "THONG_TIN_DANG_NHAP.txt").write_text(
        f"Broker: {args.host}:{args.port}\nTopic: iot/esp32_01/lm393\n"
        f"Wi-Fi setup AP: ESP32-IOT-Setup\nWi-Fi setup AP password: {credentials['ap_password']}\n"
        f"Backend user: mqtt_admin\nBackend password: {credentials['admin_password']}\n"
        "Wi-Fi portal: http://192.168.4.1\nBackend: http://127.0.0.1:8000/docs\n"
        "Mat khau Wi-Fi nha ban nhap tren ESP32; khong nam trong file nay.\n", encoding="utf-8")
    from prepare_broker_v2 import prepare
    prepare()
    print(f"Configured MQTT at {args.host}:{args.port}. Credentials saved locally (not printed).")


if __name__ == "__main__":
    main()
