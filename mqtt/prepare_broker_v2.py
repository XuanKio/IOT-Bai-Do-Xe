"""Migrate the local broker to live, per-device access control without changing device passwords.

Run while this project's broker is stopped on the first migration. Later runs only regenerate
paths/listeners; they never overwrite live device passwords or re-enable revoked clients.
"""
import json
import secrets
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "mqtt/runtime"


def prepare():
    credentials_path = RUNTIME / "credentials.json"
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    if "broker_admin" not in credentials:
        credentials["broker_admin"] = secrets.token_hex(24)
        credentials_path.write_text(json.dumps(credentials, indent=2), encoding="utf-8")
    config = RUNTIME / "dynamic-security.json"
    if not (RUNTIME / "broker-v2.ready").exists():
        if not config.exists():
            result = subprocess.run([str(ROOT / ".tools/mosquitto/mosquitto_ctrl.exe"), "dynsec", "init",
                str(config), "broker_admin", credentials["broker_admin"]], capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError("Could not initialize Dynamic Security")
        data = json.loads(config.read_text(encoding="utf-8"))
        def acl(kind, topic):
            return {"acltype": kind, "topic": topic, "allow": True}
        roles = [
            {"rolename": "device", "acls": [
                *[acl("publishClientSend", f"iot/%u/{suffix}") for suffix in ("lm393", "ack", "status")],
                acl("subscribePattern", "iot/%u/commands"),
                acl("unsubscribePattern", "iot/%u/commands"),
                acl("publishClientReceive", "iot/%u/commands")]},
            {"rolename": "backend", "acls": [
                acl("publishClientSend", "iot/+/commands"),
                *[acl(kind, f"iot/+/{suffix}") for kind in ("subscribePattern", "publishClientReceive", "unsubscribePattern")
                  for suffix in ("lm393", "ack", "status")]]},
            {"rolename": "simulator", "acls": [acl("publishClientSend", "iot/simulator/lm393")]},
        ]
        for role in roles:
            if not any(existing["rolename"] == role["rolename"] for existing in data["roles"]):
                data["roles"].append(role)
        passwords = {}
        for line in (RUNTIME / "passwords").read_text().splitlines():
            name, encoded = line.split(":", 1)
            passwords[name] = encoded
        for username, role in (("esp32_01", "device"), ("receiver", "backend"), ("simulator", "simulator")):
            if not any(client["username"] == username for client in data["clients"]):
                data["clients"].append({"username": username, "encoded_password": passwords[username],
                                       "roles": [{"rolename": role, "priority": 1}]})
        data["defaultACLAccess"] = {"publishClientSend": False, "publishClientReceive": False,
                                    "subscribe": False, "unsubscribe": True}
        config.write_text(json.dumps(data, indent=2), encoding="utf-8")
        (RUNTIME / "broker-v2.ready").write_text("2\n", encoding="utf-8")
    connection = json.loads((RUNTIME / "connection.json").read_text())
    (RUNTIME / "mosquitto.conf").write_text(
        f"listener {connection['port']} 0.0.0.0\n"
        "allow_anonymous false\n"
        f"plugin {(ROOT / '.tools/mosquitto/mosquitto_dynamic_security.dll').as_posix()}\n"
        f"plugin_opt_config_file {config.as_posix()}\n"
        "persistence false\nlog_dest stdout\nlog_type error\nlog_type warning\nlog_type notice\n", encoding="utf-8")
    env_path = RUNTIME / "backend.env"
    lines = [line for line in env_path.read_text().splitlines() if not line.startswith(("MQTT_ADMIN_", "BACKGROUND_ENABLED="))]
    lines.extend(["MQTT_ADMIN_USERNAME=broker_admin", f"MQTT_ADMIN_PASSWORD={credentials['broker_admin']}", "BACKGROUND_ENABLED=1"])
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Broker prepared for Dynamic Security. Existing ESP32 credentials preserved.")


if __name__ == "__main__":
    prepare()
