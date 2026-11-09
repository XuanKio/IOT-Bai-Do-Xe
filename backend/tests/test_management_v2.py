from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app import main as M
from app.broker_admin import BrokerUnavailable
from app.domain import AlertDetails, DeviceCommand, DeviceDetails, DeviceGrant, ParkingEvent
from app.domain_service import acknowledge_command, persist_reading, runtime_tick
from app.mqtt_receiver import AckMessage, TelemetryMessage


def reading(level1=1, level2=1, **extra):
    return TelemetryMessage(device_id="esp32_01", uptime_s=10, do=level1,
        detected=level1 == 0, do2=level2, detected2=level2 == 0, **extra)


@pytest.fixture
def api(fake_broker):
    with TestClient(M.app) as client:
        published = []
        M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True,
            publish_command=lambda code, value: published.append((code, value)), stop=lambda: None)
        M.app.state.broker_admin = fake_broker
        with M.Sessions() as db:
            device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
            did = device.id
            for name, role in (("admin_v2", "admin"), ("operator_v2", "operator"), ("viewer_v2", "viewer"), ("stranger_v2", "operator")):
                user = M.User(username=name, password_hash=M.hasher.hash("password-for-tests"), role=role)
                db.add(user)
                db.flush()
                if name in {"operator_v2", "viewer_v2"}:
                    db.add(DeviceGrant(device_id=did, user_id=user.id,
                        can_control=role == "operator", can_configure=role == "operator"))
            db.commit()
        headers = {}
        for name in ("admin_v2", "operator_v2", "viewer_v2", "stranger_v2"):
            token = client.post("/auth/login", json={"username": name, "password": "password-for-tests"}).json()["access_token"]
            headers[name] = {"Authorization": "Bearer " + token}
        try:
            yield client, headers, did, published
        finally:
            M.app.state.mqtt_receiver = None


def test_scope_and_grant_revocation(api):
    client, headers, did, _ = api
    stranger = headers["stranger_v2"]
    for path in (f"/devices/{did}", "/telemetry/latest", "/telemetry", "/telemetry/statistics", "/telemetry/export.csv"):
        assert client.get(path, headers=stranger).status_code == 404
    assert client.get("/devices", headers=stranger).json() == []
    assert client.get("/parking/slots", headers=stranger).json() == []
    assert client.get("/dashboard", headers=stranger).json()["capacity"] == 0
    assert client.get("/alerts", headers=stranger).json() == []
    assert client.get("/parking/events", headers=stranger).json() == []
    assert client.get("/parking/overview", headers=headers["viewer_v2"]).json()["capacity"] == 2
    with M.Sessions() as db:
        viewer = db.scalar(select(M.User).where(M.User.username == "viewer_v2"))
        viewer_id = viewer.id
    assert client.delete(f"/devices/{did}/grants/{viewer_id}", headers=headers["admin_v2"]).status_code == 204
    assert client.get("/parking/overview", headers=headers["viewer_v2"]).json()["capacity"] == 0


def test_real_provisioning_contract_and_fail_closed(api, fake_broker):
    client, headers, _, _ = api
    admin = headers["admin_v2"]
    response = client.post("/devices", headers=admin, json={"code": "new_node", "name": "New node"})
    did = response.json()["id"]
    assert client.patch(f"/devices/{did}", headers=admin, json={"status": "active"}).status_code == 409
    M.app.state.broker_admin = None
    assert client.post(f"/devices/{did}/provision", headers=admin).status_code == 503
    assert client.get(f"/devices/{did}", headers=admin).json()["status"] == "registered"
    M.app.state.broker_admin = fake_broker
    response = client.post(f"/devices/{did}/provision", headers=admin)
    assert response.status_code == 200
    password = response.json()["mqtt_password"]
    assert fake_broker.clients["new_node"]["password"] == password
    assert "mqtt_password" not in client.get(f"/devices/{did}", headers=admin).json()
    assert password not in str(client.get("/audit-logs", headers=admin).json())
    assert client.patch(f"/devices/{did}", headers=admin, json={"status": "active"}).status_code == 200
    assert client.patch(f"/devices/{did}", headers=admin, json={"status": "revoked"}).status_code == 200
    assert fake_broker.clients["new_node"]["enabled"] is False
    assert client.patch(f"/devices/{did}", headers=admin, json={"status": "decommissioned"}).status_code == 200
    assert client.patch(f"/devices/{did}", headers=admin, json={"status": "provisioned"}).status_code == 409


def test_broker_failure_does_not_claim_revocation_succeeded(api):
    client, headers, did, _ = api
    def fail(*args):
        raise BrokerUnavailable("test outage")
    M.app.state.broker_admin = SimpleNamespace(set_enabled=fail)
    assert client.patch(f"/devices/{did}", headers=headers["admin_v2"], json={"status": "revoked"}).status_code == 503
    assert client.get(f"/devices/{did}", headers=headers["admin_v2"]).json()["status"] == "active"


def test_deduplication_out_of_order_and_old_boot(api):
    _, _, _, _ = api
    assert persist_reading(reading(boot_id="11111111", seq=1), M.now())
    assert not persist_reading(reading(0, 0, boot_id="11111111", seq=1), M.now())
    assert not persist_reading(reading(0, 0, boot_id="11111111", seq=0), M.now())
    assert persist_reading(reading(0, 1, boot_id="11111111", seq=2), M.now())
    assert persist_reading(reading(1, 0, boot_id="22222222", seq=0), M.now())
    assert not persist_reading(reading(0, 0, boot_id="11111111", seq=3), M.now())
    with M.Sessions() as db:
        assert db.scalar(select(func.count()).select_from(M.Telemetry)) == 3


def test_commands_require_scope_and_device_ack(api):
    client, headers, did, published = api
    persist_reading(reading(boot_id="11111111", seq=1), M.now())
    body = {"action": "configure", "report_interval_ms": 2000, "idempotency_key": "configure-1"}
    assert client.post(f"/devices/{did}/commands", headers=headers["viewer_v2"], json=body).status_code == 403
    response = client.post(f"/devices/{did}/commands", headers=headers["operator_v2"], json=body)
    assert response.status_code == 202
    command_id = response.json()["id"]
    assert response.json()["status"] == "queued"
    assert client.post(f"/devices/{did}/commands", headers=headers["operator_v2"], json=body).json()["id"] == command_id
    assert client.post(f"/devices/{did}/commands", headers=headers["operator_v2"], json={**body, "report_interval_ms": 3000}).status_code == 409
    runtime_tick()
    assert len(published) == 1
    assert published[0][1]["boot_id"] == "11111111"
    assert client.get(f"/commands/{command_id}", headers=headers["viewer_v2"]).status_code == 403
    acknowledge_command(AckMessage(device_id="other", command_id=command_id, status="succeeded",
                                   result={"report_interval_ms": 2000}), M.now())
    assert client.get(f"/commands/{command_id}", headers=headers["operator_v2"]).json()["status"] == "sent"
    acknowledge_command(AckMessage(device_id="esp32_01", command_id=command_id, status="succeeded",
                                   result={"report_interval_ms": 2000}), M.now())
    assert client.get(f"/commands/{command_id}", headers=headers["operator_v2"]).json()["status"] == "acknowledged"
    assert client.get(f"/devices/{did}/configuration", headers=headers["operator_v2"]).json()["report_interval_ms"] == 2000
    acknowledge_command(AckMessage(device_id="esp32_01", command_id=command_id, status="failed"), M.now())
    assert client.get(f"/commands/{command_id}", headers=headers["operator_v2"]).json()["status"] == "acknowledged"


def test_command_timeout_and_no_late_success(api):
    client, headers, did, _ = api
    persist_reading(reading(boot_id="11111111", seq=1), M.now())
    response = client.post(f"/devices/{did}/commands", headers=headers["admin_v2"], json={"action": "ping"})
    command_id = response.json()["id"]
    with M.Sessions() as db:
        db.get(DeviceCommand, command_id).expires_at = M.now() - timedelta(seconds=1)
        db.commit()
    runtime_tick()
    acknowledge_command(AckMessage(device_id="esp32_01", command_id=command_id, status="succeeded"), M.now())
    assert client.get(f"/commands/{command_id}", headers=headers["admin_v2"]).json()["status"] == "timed_out"
    assert not any(alert["kind"] == "command_timeout" for alert in client.get("/alerts", headers=headers["admin_v2"]).json())
    with M.Sessions() as db:
        assert not db.scalar(select(AlertDetails).where(AlertDetails.kind == "command_timeout"))


def test_full_alerts_resolve_without_acknowledgement_and_stay_scoped(api):
    client, headers, did, _ = api
    persist_reading(reading(0, 0), M.now())
    runtime_tick(); runtime_tick()
    alerts = client.get("/alerts?active_only=true", headers=headers["operator_v2"]).json()
    full = [alert for alert in alerts if alert["kind"] == "parking_full"]
    assert len(full) == 1
    aid = full[0]["id"]
    persist_reading(reading(1, 0), M.now())
    runtime_tick()
    resolved = [alert for alert in client.get("/alerts", headers=headers["operator_v2"]).json() if alert["id"] == aid][0]
    assert not resolved["active"] and resolved["resolved_at"] and "acknowledged" not in resolved and "acknowledged_by" not in resolved
    with M.Sessions() as db:
        db.get(DeviceDetails, did).last_seen = M.now() - timedelta(seconds=20)
        db.commit()
    runtime_tick(); runtime_tick()
    assert client.get("/dashboard", headers=headers["operator_v2"]).json()["unknown"] == 2
    offline = [alert for alert in client.get("/alerts?active_only=true", headers=headers["operator_v2"]).json() if alert["kind"] == "device_offline"]
    assert offline == []
    with M.Sessions() as db:
        assert not db.scalar(select(AlertDetails).where(AlertDetails.kind == "device_offline"))
    persist_reading(reading(1, 1), M.now())
    runtime_tick()
    assert not [alert for alert in client.get("/alerts?active_only=true", headers=headers["operator_v2"]).json() if alert["kind"] == "device_offline"]
    assert client.get("/alerts", headers=headers["stranger_v2"]).json() == []


def test_old_nonparking_alerts_are_retired_and_hidden(api):
    client, headers, did, _ = api
    with M.Sessions() as db:
        for kind in ("device_offline", "command_timeout"):
            alert = M.Alert(message="Old alert")
            db.add(alert)
            db.flush()
            db.add(AlertDetails(alert_id=alert.id, device_id=did, kind=kind, active_key=f"{did}:{kind}"))
        db.commit()
    runtime_tick()
    assert client.get("/alerts?limit=1", headers=headers["admin_v2"]).json() == []
    with M.Sessions() as db:
        old = db.scalars(select(AlertDetails).where(AlertDetails.kind != "parking_full")).all()
        assert len(old) == 2
        assert all(a.active_key is None and a.resolved_at for a in old)
    result = client.put(f"/devices/{did}/rules", headers=headers["admin_v2"],
        json={"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 15})
    assert result.status_code == 200
    assert result.json()["offline_enabled"] is False
    assert result.json()["offline_timeout_s"] == 15


def test_time_search_export_statistics_and_events(api):
    client, headers, _, _ = api
    persist_reading(reading(0, 1), M.now() - timedelta(hours=2))
    persist_reading(reading(1, 0), M.now())
    viewer = headers["operator_v2"]
    from_at = (M.now() - timedelta(hours=1)).isoformat()
    response = client.get("/telemetry", headers=viewer, params={"from_at": from_at})
    assert len(response.json()) == 1
    assert client.get("/telemetry", headers=viewer, params={"from_at": "2026-01-01T00:00:00"}).status_code == 422
    assert client.get("/telemetry", headers=viewer, params={"from_at": M.now().isoformat(), "to_at": from_at}).status_code == 422
    csv = client.get("/telemetry/export.csv", headers=viewer, params={"from_at": from_at})
    assert csv.status_code == 200 and len(csv.text.strip().splitlines()) == 3
    stats = client.get("/telemetry/statistics", headers=viewer).json()
    assert stats["basis"] == "sample_count_not_parking_duration"
    assert sum(bucket["samples"] for bucket in stats["buckets"]) == 4
    assert client.get("/parking/events", headers=viewer).json()


def servo_reading(mode="auto", revision=0, boot="11111111", seq=1):
    state = {"mode": mode, "target": "closed", "pwm_ready": True,
             "revision": revision, "close_remaining_ms": 0}
    return TelemetryMessage(**{**reading(boot_id=boot, seq=seq).model_dump(),
        "gate_control": {"entrance": {**state, "servo_gpio": 18},
                         "exit": {**state, "servo_gpio": 19}}})


def gate_ack(command, **changes):
    return AckMessage(device_id="esp32_01", command_id=command["id"], boot_id="11111111",
        status="succeeded", result={"gate": "entrance", "revision": command["arguments"]["revision"],
            "mode": "manual", "target": "open", "pwm_ready": True, **changes})


def test_gate_commands_are_admin_only_and_require_current_firmware(api):
    client, headers, did, _ = api
    path = f"/devices/{did}/commands"
    body = {"action": "gate_mode", "gate": "entrance", "mode": "manual"}
    persist_reading(reading(boot_id="11111111", seq=1), M.now())
    assert client.post(path, headers=headers["admin_v2"], json=body).status_code == 409
    persist_reading(servo_reading(seq=2), M.now())
    for name in ("operator_v2", "viewer_v2", "stranger_v2"):
        assert client.post(path, headers=headers[name], json=body).status_code == 403
    assert client.get(f"/devices/{did}/gates", headers=headers["stranger_v2"]).status_code == 404
    assert client.get(f"/devices/{did}/gates", headers=headers["viewer_v2"]).status_code == 403
    assert client.post(path, headers=headers["admin_v2"], json={"action": "gate", "gate": "entrance", "target": "open"}).status_code == 409
    assert client.post(path, headers=headers["admin_v2"], json={**body, "target": "open"}).status_code == 422
    command = client.post(path, headers=headers["admin_v2"], json=body)
    assert command.status_code == 202
    assert client.post(path, headers=headers["admin_v2"], json=body).status_code == 409
    # The other gate has an independent command slot.
    assert client.post(path, headers=headers["admin_v2"], json={**body, "gate": "exit"}).status_code == 202


def test_gate_ack_requires_matching_boot_gate_and_revision(api):
    client, headers, did, published = api
    persist_reading(servo_reading(mode="manual"), M.now())
    path, admin = f"/devices/{did}/commands", headers["admin_v2"]
    body = {"action": "gate", "gate": "entrance", "target": "open", "idempotency_key": "gate-1"}
    command = client.post(path, headers=admin, json=body).json()
    assert client.post(path, headers=admin, json=body).json()["id"] == command["id"]
    runtime_tick()
    assert published[-1][1]["arguments"]["revision"] == 1
    bad_boot = gate_ack(command).model_copy(update={"boot_id": "22222222"})
    acknowledge_command(bad_boot, M.now())
    assert client.get(f"/commands/{command['id']}", headers=admin).json()["status"] == "sent"
    acknowledge_command(gate_ack(command, gate="exit"), M.now())
    assert client.get(f"/commands/{command['id']}", headers=admin).json()["status"] == "failed"
    command = client.post(path, headers=admin, json={**body, "idempotency_key": "gate-2"}).json()
    assert command["arguments"]["revision"] == 2
    acknowledge_command(gate_ack(command), M.now())
    assert client.get(f"/commands/{command['id']}", headers=admin).json()["status"] == "acknowledged"


def test_gate_commands_cancel_after_device_reboot(api):
    client, headers, did, published = api
    persist_reading(servo_reading(mode="manual"), M.now())
    command = client.post(f"/devices/{did}/commands", headers=headers["admin_v2"],
        json={"action": "gate", "gate": "entrance", "target": "open"}).json()
    persist_reading(servo_reading(mode="manual", boot="22222222", seq=0), M.now())
    runtime_tick()
    assert not published
    assert client.get(f"/commands/{command['id']}", headers=headers["admin_v2"]).json()["status"] == "cancelled"


def test_gate_state_is_unknown_when_expired_and_does_not_add_alerts(api, monkeypatch):
    client, headers, did, _ = api
    start = M.now()
    persist_reading(servo_reading(), start)
    path = f"/devices/{did}/gates"
    view = client.get(path, headers=headers["admin_v2"]).json()
    assert view["fresh"] and len(view["gates"]) == 2
    assert all(g["position_verified"] is False for g in view["gates"])
    assert client.get("/dashboard", headers=headers["admin_v2"]).json()["capacity"] == 2
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=11))
    view = client.get(path, headers=headers["admin_v2"]).json()
    assert not view["fresh"] and all(g["target"] is None and g["mode"] is None for g in view["gates"])
    runtime_tick()
    assert client.get("/alerts", headers=headers["admin_v2"]).json() == []


def test_gate_map_presence_requires_matching_live_sensor_data(api, monkeypatch):
    from app.domain import LiveGateSensors
    client, headers, did, _ = api
    start = M.now()
    payload = servo_reading().model_dump()
    payload["gate_sensors"] = {
        "entrance": {"gpio": 32, "do": 0, "detected": True},
        "exit": {"gpio": 33, "do": 1, "detected": False},
    }
    persist_reading(TelemetryMessage(**payload), start)
    path = f"/devices/{did}/gates"
    def presence():
        return {g["id"]: g["detected"] for g in client.get(path, headers=headers["admin_v2"]).json()["gates"]}
    assert presence() == {"entrance": True, "exit": False}
    assert client.get("/dashboard", headers=headers["admin_v2"]).json()["capacity"] == 2
    with M.Sessions() as db:
        sensors = db.get(LiveGateSensors, "esp32_01")
        sensors.boot_id = "22222222"
        db.commit()
    assert presence() == {"entrance": None, "exit": None}
    with M.Sessions() as db:
        sensors = db.get(LiveGateSensors, "esp32_01")
        sensors.boot_id = "11111111"
        sensors.received_at = start - timedelta(seconds=1)
        db.commit()
    assert presence() == {"entrance": None, "exit": None}
    with M.Sessions() as db:
        db.get(LiveGateSensors, "esp32_01").received_at = start
        db.commit()
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=11))
    assert presence() == {"entrance": None, "exit": None}
