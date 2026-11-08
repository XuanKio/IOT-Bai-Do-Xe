"""Regression coverage for DHCP changes without resetting live MQTT credentials."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "sync_network", Path(__file__).resolve().parents[2] / "mqtt" / "sync_network.py",
)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


@pytest.fixture
def configured_root(tmp_path):
    runtime = tmp_path / "mqtt" / "runtime"
    runtime.mkdir(parents=True)
    (tmp_path / "esp32_core").mkdir()
    files = {
        runtime / "connection.json": json.dumps({"host": "192.168.1.7", "port": 1884}),
        runtime / "mosquitto.conf": (
            "listener 1884 127.0.0.1\nlistener 1884 192.168.1.7\n"
            "allow_anonymous false\nplugin dynamic-security.dll\nplugin_opt_config_file security.json\n"
        ),
        runtime / "THONG_TIN_DANG_NHAP.txt": "Broker: 192.168.1.7:1884\nBackend password: unchanged\n",
        tmp_path / "esp32_core" / "config.local.h": (
            'constexpr char MQTT_HOST[] = "192.168.1.7";\n'
            'constexpr char MQTT_PASSWORD[] = "unchanged";\n'
        ),
        runtime / "backend.env": "MQTT_HOST=127.0.0.1\nMQTT_PASSWORD=unchanged\n",
        runtime / "credentials.json": '{"receiver": "unchanged"}',
        runtime / "dynamic-security.json": '{"clients": [{"username": "revoked", "disabled": true}]}',
    }
    for path, text in files.items():
        path.write_bytes(text.encode("utf-8"))
    return tmp_path, files


def test_dhcp_change_updates_endpoints_and_preserves_security(configured_root):
    root, before = configured_root
    assert network.sync_network(root, "192.168.1.6")
    runtime = root / "mqtt" / "runtime"
    assert json.loads((runtime / "connection.json").read_text())["host"] == "192.168.1.6"
    assert (runtime / "mosquitto.conf").read_text() == before[runtime / "mosquitto.conf"].replace(
        "listener 1884 192.168.1.7", "listener 1884 192.168.1.6",
    )
    for path, content in before.items():
        if path.name in {"backend.env", "credentials.json", "dynamic-security.json"}:
            assert path.read_bytes() == content.encode()
    assert (root / "esp32_core" / "config.local.h").read_text() == (
        before[root / "esp32_core" / "config.local.h"].replace("192.168.1.7", "192.168.1.6")
    )
    assert (runtime / "THONG_TIN_DANG_NHAP.txt").read_text() == (
        before[runtime / "THONG_TIN_DANG_NHAP.txt"].replace("192.168.1.7", "192.168.1.6")
    )
    after = {path: path.read_bytes() for path in before}
    assert not network.sync_network(root, "192.168.1.6")
    assert all(path.read_bytes() == content for path, content in after.items())


@pytest.mark.parametrize("host", ["0.0.0.0", "127.0.0.1", "224.0.0.1", "169.254.1.2", "bad-host"])
def test_invalid_address_leaves_configuration_untouched(configured_root, host):
    root, before = configured_root
    with pytest.raises(ValueError):
        network.sync_network(root, host)
    assert all(path.read_bytes() == content.encode() for path, content in before.items())


def test_unexpected_listener_leaves_other_files_untouched(configured_root):
    root, before = configured_root
    config = root / "mqtt" / "runtime" / "mosquitto.conf"
    config.write_text("listener 1884 127.0.0.1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Expected one LAN listener"):
        network.sync_network(root, "192.168.1.6")
    assert all(path.read_bytes() == content.encode() for path, content in before.items() if path != config)


def test_roaming_listener_survives_subsequent_dhcp_changes(configured_root):
    root, before = configured_root
    path = root / "mqtt" / "runtime" / "mosquitto.conf"
    assert network.prepare_roaming_listener(root)
    assert path.read_text() == (
        "listener 1884 0.0.0.0\nallow_anonymous false\n"
        "plugin dynamic-security.dll\nplugin_opt_config_file security.json\n"
    )
    assert not network.prepare_roaming_listener(root)
    assert network.sync_network(root, "192.168.2.8")
    assert path.read_text().count("listener ") == 1
    assert "listener 1884 0.0.0.0" in path.read_text()
    for name in ("backend.env", "credentials.json", "dynamic-security.json"):
        target = root / "mqtt" / "runtime" / name
        assert target.read_bytes() == before[target].encode()
