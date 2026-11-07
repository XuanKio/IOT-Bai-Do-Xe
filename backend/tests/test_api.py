from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from app.main import app, Sessions, User, hasher, store_reading, now
from app.mqtt_receiver import TelemetryMessage
from app.main import Device
from app.domain import DeviceGrant
from sqlalchemy import select


def grant_physical(db, user):
    db.flush()
    device = db.scalar(select(Device).where(Device.code == "esp32_01"))
    db.add(DeviceGrant(device_id=device.id, user_id=user.id))


def test_management_flow(fake_broker):
    with TestClient(app) as client:
        app.state.broker_admin = fake_broker
        with Sessions() as db:
            db.add(User(username="admin", password_hash=hasher.hash("admin-password"), role="admin"))
            db.commit()
        assert client.get("/devices").status_code in (401, 403)
        assert client.post("/auth/login", json={"username": "admin", "password": "wrong-password"}).status_code == 401
        token = client.post("/auth/login", json={"username": "admin", "password": "admin-password"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        assert client.post("/users", headers=headers, json={"username": "viewer", "password": "viewer-password", "role": "viewer"}).status_code == 201
        vt = client.post("/auth/login", json={"username": "viewer", "password": "viewer-password"}).json()["access_token"]
        vh = {"Authorization": "Bearer " + vt}
        with Sessions() as db:
            grant_physical(db, db.scalar(select(User).where(User.username == "viewer")))
            db.commit()
        assert client.post("/devices", headers=vh, json={"code": "esp32-01", "name": "Gate"}).status_code == 403
        result = client.post("/devices", headers=headers, json={"code": "esp32-01", "name": "Gate"})
        assert result.status_code == 201
        did = result.json()["id"]
        assert client.post("/devices", headers=headers, json={"code": "esp32-01", "name": "Duplicate"}).status_code == 409
        assert client.patch(f"/devices/{did}", headers=headers, json={"status": "active"}).status_code == 409
        assert client.post(f"/devices/{did}/provision", headers=headers).status_code == 200
        for state in ("active", "revoked", "decommissioned"):
            assert client.patch(f"/devices/{did}", headers=headers, json={"status": state}).status_code == 200
        assert client.patch(f"/devices/{did}", headers=headers, json={"status": "active"}).status_code == 409
        summary = client.get("/parking/overview", headers=vh).json()
        assert summary["unknown"] == 2 and summary["available"] == 0
        assert client.post(f"/devices/{did}/commands", headers=headers, json={"action": "ping"}).status_code == 409
        assert client.get("/audit-logs", headers=vh).status_code == 403
        assert len(client.get("/audit-logs", headers=headers).json()) >= 5
        assert client.post("/auth/logout", headers=vh).status_code == 204
        assert client.get("/auth/me", headers=vh).status_code == 401
        assert client.post("/auth/password", headers=headers, json={"old_password": "admin-password", "new_password": "new-admin-password"}).status_code == 204
        assert client.get("/auth/me", headers=headers).status_code == 401


def test_telemetry_storage_auth_and_simulation_separation():
    with TestClient(app) as client:
        with Sessions() as db:
            user = User(username="mqtt_viewer", password_hash=hasher.hash("viewer-mqtt-password"), role="operator")
            db.add(user)
            grant_physical(db, user)
            db.add(User(username="telemetry_admin", password_hash=hasher.hash("admin-mqtt-password"), role="admin"))
            db.commit()
        assert client.get("/telemetry/latest").status_code in (401, 403)
        token = client.post("/auth/login", json={"username": "mqtt_viewer", "password": "viewer-mqtt-password"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        admin_token = client.post("/auth/login", json={"username": "telemetry_admin", "password": "admin-mqtt-password"}).json()["access_token"]
        admin_headers = {"Authorization": "Bearer " + admin_token}
        assert client.get("/telemetry/latest", headers=headers).json() is None
        store_reading(TelemetryMessage(device_id="simulator", uptime_s=1, do=0, detected=True), now())
        assert client.get("/telemetry/latest", headers=headers).json() is None
        assert client.get("/telemetry/latest?device_id=simulator", headers=headers).status_code == 404
        simulated = client.get("/telemetry/latest?device_id=simulator", headers=admin_headers).json()
        assert simulated["simulated"] is True and simulated["fresh"] is False
        store_reading(TelemetryMessage(device_id="esp32_01", uptime_s=2, do=1, detected=False), now())
        reading = client.get("/telemetry/latest", headers=headers).json()
        assert reading["do"] == 1 and reading["detected"] is False
        assert reading["simulated"] is False and reading["fresh"] is False
        assert reading["received_at"].endswith("+00:00")
        assert len(client.get("/telemetry", headers=headers).json()) == 1
        assert client.get("/telemetry?limit=201", headers=headers).status_code == 422


def test_two_slot_occupancy_and_freshness(monkeypatch):
    with TestClient(app) as client:
        with Sessions() as db:
            user = User(username="slots_viewer", password_hash=hasher.hash("viewer-slots-password"), role="operator")
            db.add(user)
            grant_physical(db, user)
            db.commit()
        token = client.post("/auth/login", json={"username": "slots_viewer", "password": "viewer-slots-password"}).json()["access_token"]
        headers = {"Authorization": "Bearer " + token}
        receiver = SimpleNamespace(connected=True, subscribed=True)
        app.state.mqtt_receiver = receiver
        try:
            for level1, level2 in [(0, 0), (0, 1), (1, 0), (1, 1)]:
                item = TelemetryMessage(device_id="esp32_01", uptime_s=10,
                    do=level1, detected=level1 == 0, do2=level2, detected2=level2 == 0)
                store_reading(item, now())
                slots = client.get("/parking/slots", headers=headers).json()
                assert [(slot["name"], slot["gpio"], slot["occupied"]) for slot in slots] == [
                    ("P1", 27, level1 == 0), ("P2", 26, level2 == 0)]
                summary = client.get("/dashboard", headers=headers).json()
                assert summary["occupied"] == int(level1 == 0) + int(level2 == 0)
                assert summary["available"] == int(level1 == 1) + int(level2 == 1)
                assert summary["unknown"] == 0
                telemetry = client.get("/telemetry/latest", headers=headers).json()
                assert [slot["do"] for slot in telemetry["slots"]] == [level1, level2]

            store_reading(TelemetryMessage(device_id="simulator", uptime_s=1, do=0, detected=True,
                                          do2=0, detected2=True), now())
            assert client.get("/dashboard", headers=headers).json()["available"] == 2
            receiver.connected = False
            assert client.get("/dashboard", headers=headers).json()["unknown"] == 2
            receiver.connected = True
            from app import main as M
            at = now() + timedelta(seconds=11)
            monkeypatch.setattr(M, "now", lambda: at)
            assert client.get("/dashboard", headers=headers).json()["unknown"] == 2
            assert all(slot["occupied"] is None for slot in client.get("/parking/slots", headers=headers).json())
        finally:
            app.state.mqtt_receiver = None
