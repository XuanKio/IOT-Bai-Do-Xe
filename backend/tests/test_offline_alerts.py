from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app import main as M
from app.domain import AlertDetails, DeviceDetails, DeviceGrant
from app.domain_service import persist_reading, receive_status, runtime_tick
from app.mqtt_receiver import StatusMessage, TelemetryMessage


def reading(level1=1, level2=1):
    return TelemetryMessage(device_id="esp32_01", uptime_s=10, do=level1,
        detected=level1 == 0, do2=level2, detected2=level2 == 0)


class Clock:
    def __init__(self, monkeypatch):
        self.now = M.now()
        monkeypatch.setattr(M, "now", lambda: self.now)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def env(fake_broker, monkeypatch):
    clock = Clock(monkeypatch)
    with TestClient(M.app) as client:
        M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True,
            publish_command=lambda code, value: None, stop=lambda: None)
        M.app.state.broker_admin = fake_broker
        with M.Sessions() as db:
            did = db.scalar(select(M.Device.id).where(M.Device.code == "esp32_01"))
            db.get(DeviceDetails, did).offline_alert = True
            for name, role in (("admin_e2", "admin"), ("operator_e2", "operator"),
                               ("viewer_e2", "viewer"), ("stranger_e2", "operator")):
                user = M.User(username=name, password_hash=M.hasher.hash("password-for-tests"), role=role)
                db.add(user)
                db.flush()
                if name in {"operator_e2", "viewer_e2"}:
                    db.add(DeviceGrant(device_id=did, user_id=user.id,
                        can_control=role == "operator", can_configure=role == "operator"))
            db.commit()
        headers = {}
        for name in ("admin_e2", "operator_e2", "viewer_e2", "stranger_e2"):
            token = client.post("/auth/login", json={"username": name, "password": "password-for-tests"}).json()["access_token"]
            headers[name] = {"Authorization": "Bearer " + token}
        try:
            yield client, headers, did, clock
        finally:
            M.app.state.mqtt_receiver = None


def offline_alerts(client, headers, **query):
    suffix = "?active_only=true" if query.get("active_only") else ""
    return [a for a in client.get("/alerts" + suffix, headers=headers["admin_e2"]).json() if a["kind"] == "device_offline"]


def rows():
    with M.Sessions() as db:
        return db.scalar(select(func.count()).select_from(AlertDetails).where(AlertDetails.kind == "device_offline"))


def start_online(clock):
    """A device that has reported once while the receiver was ready."""
    runtime_tick()
    persist_reading(reading(), clock.now)
    runtime_tick()


def go_silent(clock, seconds=11):
    clock.advance(seconds)
    runtime_tick()


def test_online_device_and_short_silence_do_not_alert(env):
    client, headers, _, clock = env
    start_online(clock)
    assert offline_alerts(client, headers) == []
    go_silent(clock, 5)
    assert offline_alerts(client, headers) == []
    assert rows() == 0


def test_silence_beyond_timeout_creates_exactly_one_alert(env):
    client, headers, did, clock = env
    start_online(clock)
    go_silent(clock)
    for _ in range(4):
        runtime_tick()
        clock.advance(1)
    alerts = offline_alerts(client, headers, active_only=True)
    assert len(alerts) == 1 and rows() == 1
    alert = alerts[0]
    assert alert["device_id"] == did and alert["active"] is True and alert["resolved_at"] is None
    assert alert["acknowledged"] is False and alert["created_at"]


def test_alert_resolves_on_return_and_new_outage_keeps_history(env):
    client, headers, _, clock = env
    start_online(clock)
    go_silent(clock)
    first = offline_alerts(client, headers, active_only=True)[0]["id"]
    clock.advance(1)
    persist_reading(reading(), clock.now)
    runtime_tick(); runtime_tick()
    assert offline_alerts(client, headers, active_only=True) == []
    resolved = [a for a in offline_alerts(client, headers) if a["id"] == first][0]
    assert resolved["active"] is False and resolved["resolved_at"]
    go_silent(clock, 12)
    runtime_tick()
    history = offline_alerts(client, headers)
    assert len(history) == 2 and rows() == 2
    assert len([a for a in history if a["active"]]) == 1
    assert [a for a in history if a["id"] == first][0]["resolved_at"] == resolved["resolved_at"]


def test_device_that_never_reported_does_not_alert(env):
    client, headers, _, clock = env
    runtime_tick()
    go_silent(clock, 120)
    runtime_tick()
    assert rows() == 0


@pytest.mark.parametrize("status", ["maintenance", "revoked", "decommissioned", "provisioned", "registered"])
def test_non_active_devices_do_not_alert(env, status):
    client, headers, did, clock = env
    start_online(clock)
    with M.Sessions() as db:
        db.get(M.Device, did).status = status
        db.commit()
    go_silent(clock, 30)
    assert rows() == 0


def test_alert_closes_when_device_enters_maintenance(env):
    client, headers, did, clock = env
    start_online(clock)
    go_silent(clock)
    assert len(offline_alerts(client, headers, active_only=True)) == 1
    with M.Sessions() as db:
        db.get(M.Device, did).status = "maintenance"
        db.commit()
    runtime_tick()
    assert offline_alerts(client, headers, active_only=True) == []
    assert rows() == 1


def test_receiver_down_or_restarting_does_not_cause_mass_alerts(env):
    client, headers, _, clock = env
    start_online(clock)
    clock.advance(60)
    M.app.state.mqtt_receiver = None
    runtime_tick(); runtime_tick()
    assert rows() == 0
    M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True,
        publish_command=lambda code, value: None, stop=lambda: None)
    runtime_tick()
    assert rows() == 0
    clock.advance(5)
    runtime_tick()
    assert rows() == 0
    clock.advance(6)
    runtime_tick()
    assert rows() == 1


def test_active_alert_survives_receiver_outage_without_duplicates(env):
    client, headers, _, clock = env
    start_online(clock)
    go_silent(clock)
    first = offline_alerts(client, headers, active_only=True)[0]["id"]
    client.post(f"/alerts/{first}/acknowledge", headers=headers["operator_e2"])
    M.app.state.mqtt_receiver = None
    clock.advance(30)
    runtime_tick(); runtime_tick()
    still = offline_alerts(client, headers, active_only=True)
    assert [a["id"] for a in still] == [first] and still[0]["acknowledged"] is True
    M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True,
        publish_command=lambda code, value: None, stop=lambda: None)
    runtime_tick()
    clock.advance(30)
    runtime_tick()
    assert [a["id"] for a in offline_alerts(client, headers, active_only=True)] == [first]
    assert rows() == 1
    persist_reading(reading(), clock.now)
    runtime_tick()
    assert offline_alerts(client, headers, active_only=True) == []
    assert rows() == 1


def test_rule_can_be_disabled_and_enabled(env):
    client, headers, did, clock = env
    admin = headers["admin_e2"]
    rules = client.get(f"/devices/{did}/rules", headers=admin).json()
    assert rules["offline_enabled"] is True
    body = {"offline_enabled": False, "full_enabled": True, "offline_timeout_s": 10}
    assert client.put(f"/devices/{did}/rules", headers=admin, json=body).json()["offline_enabled"] is False
    start_online(clock)
    go_silent(clock, 30)
    assert rows() == 0
    body["offline_enabled"] = True
    assert client.put(f"/devices/{did}/rules", headers=admin, json=body).json()["offline_enabled"] is True
    runtime_tick()
    assert len(offline_alerts(client, headers, active_only=True)) == 1
    body["offline_enabled"] = False
    client.put(f"/devices/{did}/rules", headers=admin, json=body)
    runtime_tick()
    assert offline_alerts(client, headers, active_only=True) == []
    assert rows() == 1


def test_rule_validation_and_custom_timeout(env):
    client, headers, did, clock = env
    admin = headers["admin_e2"]
    assert client.put(f"/devices/{did}/rules", headers=admin,
        json={"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 2}).status_code == 422
    assert client.put(f"/devices/{did}/rules", headers=admin,
        json={"offline_enabled": "maybe"}).status_code == 422
    client.put(f"/devices/{did}/rules", headers=admin,
        json={"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 30})
    start_online(clock)
    go_silent(clock, 20)
    assert rows() == 0
    go_silent(clock, 11)
    assert rows() == 1


def test_offline_alert_scope_and_acknowledge_rules(env):
    client, headers, did, clock = env
    start_online(clock)
    go_silent(clock)
    aid = offline_alerts(client, headers, active_only=True)[0]["id"]
    assert [a["id"] for a in client.get("/alerts", headers=headers["operator_e2"]).json()] == [aid]
    assert client.get("/alerts", headers=headers["stranger_e2"]).json() == []
    assert client.post(f"/alerts/{aid}/acknowledge", headers=headers["viewer_e2"]).status_code == 403
    assert client.post(f"/alerts/{aid}/acknowledge", headers=headers["stranger_e2"]).status_code == 404
    first = client.post(f"/alerts/{aid}/acknowledge", headers=headers["operator_e2"]).json()
    assert first["acknowledged"] is True and first["active"] is True and first["resolved_at"] is None
    assert first["kind"] == "device_offline"
    assert client.post(f"/alerts/{aid}/acknowledge", headers=headers["admin_e2"]).json() == first
    runtime_tick()
    assert offline_alerts(client, headers, active_only=True)[0]["acknowledged_by"] == first["acknowledged_by"]
    clock.advance(1)
    persist_reading(reading(), clock.now)
    runtime_tick()
    final = [a for a in offline_alerts(client, headers) if a["id"] == aid][0]
    assert final["active"] is False and final["resolved_at"]
    assert final["acknowledged"] is True and final["acknowledged_by"] == first["acknowledged_by"]
    assert final["acknowledged_at"] == first["acknowledged_at"]


def test_offline_and_parking_full_alerts_coexist(env):
    client, headers, did, clock = env
    runtime_tick()
    persist_reading(reading(0, 0), clock.now)
    runtime_tick(); runtime_tick()
    kinds = {a["kind"] for a in client.get("/alerts?active_only=true", headers=headers["admin_e2"]).json()}
    assert kinds == {"parking_full"}
    go_silent(clock)
    active = {a["kind"]: a for a in client.get("/alerts?active_only=true", headers=headers["admin_e2"]).json()}
    assert "device_offline" in active
    assert "parking_full" not in active
    with M.Sessions() as db:
        assert db.scalar(select(func.count()).select_from(AlertDetails).where(AlertDetails.kind == "parking_full")) == 1


def test_effective_timeout_waits_for_three_report_intervals(env):
    client, headers, did, clock = env
    with M.Sessions() as db:
        info = db.get(DeviceDetails, did)
        info.offline_timeout_s, info.report_interval_ms = 5, 10000
        db.commit()
    start_online(clock)
    go_silent(clock, 29)
    assert rows() == 0
    go_silent(clock, 1)
    assert len(offline_alerts(client, headers, active_only=True)) == 1


def test_lwt_offline_alerts_even_with_recent_telemetry_after_restart_grace(env):
    client, headers, _, clock = env
    start_online(clock)
    clock.advance(11)
    persist_reading(reading(), clock.now)
    receive_status(StatusMessage(device_id="esp32_01", state="offline"), clock.now)
    runtime_tick()
    assert len(offline_alerts(client, headers, active_only=True)) == 1
    clock.advance(1)
    persist_reading(reading(), clock.now)
    runtime_tick()
    assert offline_alerts(client, headers, active_only=True) == []


@pytest.mark.parametrize("ready_flag", ["connected", "subscribed"])
def test_receiver_not_fully_ready_defers_alert_and_restarts_grace(env, ready_flag):
    _, _, _, clock = env
    start_online(clock)
    setattr(M.app.state.mqtt_receiver, ready_flag, False)
    go_silent(clock, 30)
    assert rows() == 0
    setattr(M.app.state.mqtt_receiver, ready_flag, True)
    runtime_tick()
    go_silent(clock, 9)
    assert rows() == 0
    go_silent(clock, 1)
    assert rows() == 1
