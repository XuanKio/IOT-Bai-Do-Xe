from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from app import main as M
from app.domain import (DeviceBoot, DeviceDetails, DeviceGrant, HourlyOccupancy,
                        LiveTelemetry, LiveGateSensors, ParkingEvent, SeenPacket)
from app.domain_service import persist_reading, receive_status
from app.mqtt_receiver import StatusMessage, TelemetryMessage


def gate_packet(seq, entrance=1, exit=1):
    return TelemetryMessage(**{**packet(seq).model_dump(), "gate_sensors": {
        "entrance": {"gpio": 32, "do": entrance, "detected": entrance == 0},
        "exit": {"gpio": 33, "do": exit, "detected": exit == 0}}})


def test_gate_updates_do_not_add_parking_spaces_or_repeated_history(parking_api, monkeypatch):
    client, headers, _ = parking_api
    start = M.now()
    for n in range(121):
        assert persist_reading(gate_packet(n, n % 2, (n + 1) % 2), start + timedelta(seconds=n))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=120))
    latest = client.get("/telemetry/latest", headers=headers["parking_admin"]).json()
    assert latest["gate_sensors"]["fresh"]
    assert latest["gate_sensors"]["sensors"]["entrance"]["detected"] is True
    assert latest["gate_sensors"]["sensors"]["exit"]["detected"] is False
    assert client.get("/dashboard", headers=headers["parking_admin"]).json()["capacity"] == 2
    with M.Sessions() as db:
        assert db.scalar(select(func.count()).select_from(LiveGateSensors)) == 1
        assert db.scalar(select(func.count()).select_from(M.Telemetry)) == 3
        assert db.scalar(select(func.count()).select_from(M.TelemetrySlot)) == 6


def test_gate_readings_expire_and_old_firmware_clears_them(parking_api, monkeypatch):
    client, headers, _ = parking_api
    start = M.now()
    persist_reading(gate_packet(0, 0, 0), start)
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=10))
    gates = client.get("/telemetry/latest", headers=headers["parking_admin"]).json()["gate_sensors"]
    assert not gates["fresh"]
    assert all(s["detected"] is None and s["do"] is None for s in gates["sensors"].values())
    persist_reading(packet(1), start + timedelta(seconds=11))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=11))
    assert client.get("/telemetry/latest", headers=headers["parking_admin"]).json()["gate_sensors"] is None


def test_gate_readings_reject_replays_and_go_unknown_on_disconnect(parking_api):
    client, headers, _ = parking_api
    start = M.now()
    assert persist_reading(gate_packet(2, 0, 1), start)
    assert not persist_reading(gate_packet(1, 1, 0), start)
    gates = client.get("/telemetry/latest", headers=headers["parking_admin"]).json()["gate_sensors"]
    assert gates["sensors"]["entrance"]["detected"] is True
    receive_status(StatusMessage(device_id="esp32_01", state="offline", boot_id="11111111"), M.now())
    gates = client.get("/telemetry/latest", headers=headers["parking_admin"]).json()["gate_sensors"]
    assert not gates["fresh"] and gates["sensors"]["entrance"]["detected"] is None
from app.storage import advance, maintain


def packet(seq, a=1, b=0, boot="11111111"):
    return TelemetryMessage(device_id="esp32_01", uptime_s=seq, do=a, detected=a == 0,
        do2=b, detected2=b == 0, boot_id=boot, seq=seq, report_interval_ms=1000)


@pytest.fixture
def parking_api(fake_broker):
    with TestClient(M.app) as client:
        M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True, stop=lambda: None)
        M.app.state.broker_admin = fake_broker
        with M.Sessions() as db:
            did = db.scalar(select(M.Device.id).where(M.Device.code == "esp32_01"))
            for name, role, grant in [("parking_admin", "admin", False), ("driver", "viewer", True), ("outsider", "viewer", False)]:
                user = M.User(username=name, role=role, password_hash=M.hasher.hash("tests-only-password"))
                db.add(user); db.flush()
                if grant:
                    # Accidental grant flags must not reveal technical APIs.
                    db.add(DeviceGrant(device_id=did, user_id=user.id, can_control=True, can_configure=True))
            db.commit()
        headers = {}
        for name in ("parking_admin", "driver", "outsider"):
            token = client.post("/auth/login", json={"username": name, "password": "tests-only-password"}).json()["access_token"]
            headers[name] = {"Authorization": "Bearer " + token}
        yield client, headers, did


def test_live_updates_each_second_without_appending_repeated_history(parking_api, monkeypatch):
    client, headers, _ = parking_api
    start = M.now()
    for n in range(121):
        assert persist_reading(packet(n), start + timedelta(seconds=n))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=120))
    with M.Sessions() as db:
        assert db.scalar(select(func.count()).select_from(M.Telemetry)) == 3
        assert db.scalar(select(func.count()).select_from(M.TelemetrySlot)) == 6
        assert db.scalar(select(func.count()).select_from(SeenPacket)) == 0
        assert db.scalar(select(func.count()).select_from(DeviceBoot)) == 1
        assert db.get(LiveTelemetry, "esp32_01").uptime_s == 120
    latest = client.get("/telemetry/latest", headers=headers["parking_admin"]).json()
    assert latest["uptime_s"] == 120 and latest["fresh"]
    view = client.get("/parking/overview", headers=headers["driver"]).json()
    assert view["available"] == 1 and view["occupied"] == 1


def test_state_changes_are_recorded_immediately(parking_api, monkeypatch):
    client, headers, _ = parking_api
    start = M.now()
    assert persist_reading(packet(0), start)
    assert persist_reading(packet(1, 0, 0), start + timedelta(seconds=1))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=1))
    assert client.get("/parking/overview", headers=headers["driver"]).json()["occupied"] == 2
    with M.Sessions() as db:
        assert db.scalar(select(func.count()).select_from(M.Telemetry)) == 2
        assert db.scalar(select(func.count()).select_from(ParkingEvent).where(ParkingEvent.kind == "occupied")) == 1


def test_viewer_receives_only_parking_information_and_scope(parking_api):
    client, headers, did = parking_api
    persist_reading(packet(0), M.now())
    data = client.get("/parking/overview", headers=headers["driver"]).json()
    assert data["capacity"] == 2 and len(data["slots"]) == 2
    assert set(data["slots"][0]) == {"name", "status", "updated_at", "valid_until", "zone"}
    for forbidden in ("gpio", "firmware", "mqtt", "device_id", "report_interval_ms"):
        assert forbidden not in str(data).lower()
    for path in ("/devices", f"/devices/{did}", f"/devices/{did}/permissions", f"/devices/{did}/rules",
                 f"/devices/{did}/configuration", f"/devices/{did}/commands", "/telemetry",
                 "/telemetry/latest", "/telemetry/statistics", "/telemetry/export.csv", "/parking/utilization",
                 "/parking/events", "/parking/slots", "/dashboard", "/alerts", "/users", "/audit-logs", "/storage/policy"):
        assert client.get(path, headers=headers["driver"]).status_code == 403, path
    assert client.get("/parking/overview", headers=headers["outsider"]).json()["capacity"] == 0
    with M.Sessions() as db:
        user = db.scalar(select(M.User).where(M.User.username == "driver"))
        db.delete(db.get(DeviceGrant, (did, user.id))); db.commit()
    assert client.get("/parking/overview", headers=headers["driver"]).json()["capacity"] == 0
    assert client.get("/auth/me", headers=headers["driver"]).status_code == 200


def test_expired_live_state_is_unknown_even_with_retained_free_checkpoint(parking_api, monkeypatch):
    client, headers, _ = parking_api
    start = M.now()
    persist_reading(packet(0, 1, 1), start)
    persist_reading(packet(9, 1, 1), start + timedelta(seconds=9))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=18))
    assert client.get("/parking/overview", headers=headers["driver"]).json()["available"] == 2
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=19))
    result = client.get("/parking/overview", headers=headers["driver"]).json()
    assert result["available"] == 0 and result["unknown"] == 2


def test_duration_accounting_excludes_gaps_and_is_idempotent(parking_api):
    start = M.now().replace(minute=0, second=0, microsecond=0)
    persist_reading(packet(0, 1, 1), start)
    persist_reading(packet(1, 0, 1), start + timedelta(seconds=40))
    with M.Sessions() as db:
        live = db.get(LiveTelemetry, "esp32_01")
        advance(db, live, start + timedelta(seconds=55))
        advance(db, live, start + timedelta(seconds=55))
        db.commit()
        r = db.get(HourlyOccupancy, ("esp32_01", "P1", start))
        assert r.available_s == pytest.approx(10)
        assert r.occupied_s == pytest.approx(10)
        assert r.unknown_s == pytest.approx(35)


def test_forced_offline_and_maintenance_do_not_count_as_available(parking_api, monkeypatch):
    client, headers, did = parking_api
    start = M.now().replace(minute=0, second=0, microsecond=0)
    persist_reading(packet(0, 1, 1), start)
    receive_status(StatusMessage(device_id="esp32_01", state="offline", boot_id="11111111"), start + timedelta(seconds=2))
    persist_reading(packet(1, 1, 1), start + timedelta(seconds=9))
    monkeypatch.setattr(M, "now", lambda: start + timedelta(seconds=12))
    assert client.patch(f"/devices/{did}", headers=headers["parking_admin"], json={"status": "maintenance"}).status_code == 200
    assert client.get("/parking/overview", headers=headers["driver"]).json()["unknown"] == 2
    with M.Sessions() as db:
        advance(db, db.get(LiveTelemetry, "esp32_01"), start + timedelta(seconds=15)); db.commit()
        r = db.get(HourlyOccupancy, ("esp32_01", "P1", start))
        assert r.available_s == pytest.approx(5)
        assert r.unknown_s == pytest.approx(10)


def test_duration_splits_hours_without_counting_samples(parking_api):
    client, headers, _ = parking_api
    start = M.now().replace(minute=59, second=55, microsecond=0)
    persist_reading(packet(0, 0, 1), start)
    persist_reading(packet(1, 1, 0), start + timedelta(seconds=10))
    with M.Sessions() as db:
        rows = list(db.scalars(select(HourlyOccupancy).where(HourlyOccupancy.slot_name == "P1").order_by(HourlyOccupancy.hour)))
        assert [r.occupied_s for r in rows] == [5, 5]
    data = client.get("/parking/utilization", headers=headers["parking_admin"], params={
        "from_at": start.isoformat(), "to_at": (start + timedelta(seconds=10)).isoformat()}).json()
    assert data["basis"] == "observed_duration" and data["range_mode"] == "whole_hours"
    assert sum(r["occupied_seconds"] for r in data["buckets"] if r["slot"] == "P1") == 10
    assert client.get("/parking/utilization", headers=headers["parking_admin"], params={"from_at": "2026-01-01T00:00:00"}).status_code == 422


def test_retention_removes_children_but_preserves_live_state_rollup_and_boot_guard(parking_api):
    at = M.now()
    persist_reading(packet(0, boot="11111111"), at - timedelta(days=4))
    persist_reading(packet(0, boot="22222222"), at)
    with M.Sessions() as db:
        old = M.Telemetry(device_code="other", uptime_s=0, do_level=1, detected=False, received_at=at - timedelta(days=4))
        db.add(old); db.flush()
        old_id = old.id
        db.add(M.TelemetrySlot(telemetry_id=old.id, slot_name="P1", do_level=1, occupied=False))
        db.add(SeenPacket(device_code="simulator", boot_id="old", seq=1, received_at=at - timedelta(days=2)))
        db.add(ParkingEvent(device_id=1, slot_name="P1", kind="available", occupied=False, occurred_at=at - timedelta(days=91)))
        db.add(HourlyOccupancy(device_code="old", slot_name="P1", hour=at - timedelta(days=366), occupied_s=0, available_s=1, unknown_s=0))
        db.commit()
        maintain(db, at, force=True); db.commit()
        assert db.get(M.Telemetry, old_id) is None
        assert not list(db.scalars(select(M.TelemetrySlot).where(M.TelemetrySlot.telemetry_id == old_id)))
        assert db.scalar(select(func.count()).select_from(SeenPacket)) == 0
        assert db.scalar(select(func.count()).select_from(ParkingEvent).where(ParkingEvent.occurred_at < at - timedelta(days=90))) == 0
        assert db.scalar(select(func.count()).select_from(HourlyOccupancy).where(HourlyOccupancy.device_code == "old")) == 0
        assert db.get(LiveTelemetry, "esp32_01").received_at is not None
        assert db.scalar(select(func.count()).select_from(DeviceBoot)) == 2
    assert not persist_reading(packet(99, boot="11111111"), at + timedelta(seconds=1))


def test_concurrent_duplicate_packets_advance_the_watermark_once(parking_api):
    start = M.now()
    persist_reading(packet(0), start)
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda _: persist_reading(packet(1), start + timedelta(seconds=1)), range(4)))
    assert result.count(True) == 1
    with M.Sessions() as db:
        assert db.get(DeviceDetails, 1).last_seq == 1
        assert db.scalar(select(func.count()).select_from(M.Telemetry)) == 1


def test_missing_second_sensor_is_unknown_in_duration_rollup(parking_api):
    start = M.now().replace(minute=0, second=0, microsecond=0)
    one_sensor = TelemetryMessage(device_id="esp32_01", uptime_s=0, do=1, detected=False)
    persist_reading(one_sensor, start)
    with M.Sessions() as db:
        advance(db, db.get(LiveTelemetry, "esp32_01"), start + timedelta(seconds=5)); db.commit()
        row = db.get(HourlyOccupancy, ("esp32_01", "P2", start))
        assert row.available_s == 0 and row.occupied_s == 0 and row.unknown_s == 5
