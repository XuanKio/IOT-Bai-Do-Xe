"""Real API checks for the dashboard integration and effective permission contract."""
from datetime import timedelta
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as M
from app.domain import DeviceDetails, DeviceGrant


def accounts():
    with M.Sessions() as db:
        device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
        ids = {}
        for username, role, granted in (
            ("ui_admin", "admin", False), ("ui_operator", "operator", True),
            ("ui_viewer", "viewer", True), ("ui_stranger", "operator", False),
        ):
            user = M.User(username=username, role=role, password_hash=M.hasher.hash("frontend-tests-only"))
            db.add(user)
            db.flush()
            ids[username] = user.id
            if granted:
                # Viewer stays read-only even if flags were accidentally set.
                db.add(DeviceGrant(device_id=device.id, user_id=user.id, can_control=True, can_configure=False))
        db.commit()
        return device.id, ids


def login(client, username):
    response = client.post("/auth/login", json={"username": username, "password": "frontend-tests-only"})
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_dashboard_assets_are_public_but_management_stays_protected():
    with TestClient(M.app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert '<html lang="vi">' in response.text and '/assets/app.js' in response.text
        assert response.headers["cache-control"] == "no-store"
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        for path in ("app.js", "core.js", "views.js", "viewer.js", "styles.css", "viewer.css", "favicon.svg"):
            asset = client.get("/assets/" + path)
            assert asset.status_code == 200
            assert asset.headers["x-content-type-options"] == "nosniff"
            assert asset.headers["cache-control"] == "no-store"
        assert "javascript" in client.get("/assets/app.js").headers["content-type"]
        assert client.get("/assets/../backend/app/main.py").status_code == 404
        assert client.get("/users").status_code in (401, 403)
        assert client.get("/devices").status_code in (401, 403)
        assert client.get("/docs").status_code == 200
        assert "content-security-policy" not in client.get("/docs").headers


def test_permissions_expose_only_the_callers_effective_rights():
    with TestClient(M.app) as client:
        did, ids = accounts()
        headers = {name: login(client, name) for name in ids}
        path = f"/devices/{did}/permissions"
        assert client.get(path, headers=headers["ui_admin"]).json() == {
            "device_id": did, "can_read": True, "can_manage": True, "can_control": True, "can_configure": True,
        }
        assert client.get(path, headers=headers["ui_operator"]).json() == {
            "device_id": did, "can_read": True, "can_manage": False, "can_control": True, "can_configure": False,
        }
        assert client.get(path, headers=headers["ui_viewer"]).status_code == 403
        assert client.get("/parking/overview", headers=headers["ui_viewer"]).json()["capacity"] == 2
        assert client.get(path, headers=headers["ui_stranger"]).status_code == 404
        assert client.get(f"/devices/{did}/grants", headers=headers["ui_operator"]).status_code == 403
        assert client.delete(f"/devices/{did}/grants/{ids['ui_operator']}", headers=headers["ui_admin"]).status_code == 204
        assert client.get(path, headers=headers["ui_operator"]).status_code == 404


def test_frontend_receives_the_actual_staleness_threshold():
    with TestClient(M.app) as client:
        did, _ = accounts()
        with M.Sessions() as db:
            info = db.get(DeviceDetails, did)
            info.report_interval_ms = 10000
            info.offline_timeout_s = 5
            info.last_seen = M.now() - timedelta(seconds=20)
            db.commit()
        M.app.state.mqtt_receiver = SimpleNamespace(connected=True, subscribed=True, stop=lambda: None)
        response = client.get(f"/devices/{did}", headers=login(client, "ui_operator"))
        assert response.json()["effective_offline_timeout_s"] == 30
        assert response.json()["report_interval_ms"] == 10000
        assert response.json()["connectivity"] == "online"


def test_alert_review_endpoint_requires_authentication():
    with TestClient(M.app) as client:
        assert "/alerts/{alert_id}/acknowledge" in client.get("/openapi.json").json()["paths"]
        assert client.post("/alerts/1/acknowledge").status_code in {401, 403}
