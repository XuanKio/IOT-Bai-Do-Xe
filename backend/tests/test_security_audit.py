from datetime import timedelta
from types import SimpleNamespace
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import main as M
from app.broker_admin import BrokerUnavailable
from app.domain import DeviceDetails, DeviceGrant
from app.domain_service import persist_reading, runtime_tick
from app.mqtt_receiver import TelemetryMessage


def sample_reading(level1=1, level2=1, **extra):
    return TelemetryMessage(
        device_id="esp32_01",
        uptime_s=10,
        do=level1,
        detected=level1 == 0,
        do2=level2,
        detected2=level2 == 0,
        **extra,
    )


@pytest.fixture
def sec_api(fake_broker):
    with TestClient(M.app) as client:
        published = []
        M.app.state.mqtt_receiver = SimpleNamespace(
            connected=True,
            subscribed=True,
            ready_since=M.now() - timedelta(seconds=60),
            publish_command=lambda code, value: published.append((code, value)),
            stop=lambda: None,
        )
        M.app.state.broker_admin = fake_broker
        users = {}
        with M.Sessions() as db:
            device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
            did = device.id
            specs = [
                ("sec_admin", "admin", None),
                ("sec_op_full", "operator", (True, True)),
                ("sec_op_read", "operator", (False, False)),
                ("sec_op_ctrl", "operator", (True, False)),
                ("sec_op_cfg", "operator", (False, True)),
                ("sec_op_stranger", "operator", None),
                ("sec_viewer", "viewer", (False, False)),
                ("sec_viewer_stranger", "viewer", None),
            ]
            for username, role, grant_flags in specs:
                u = M.User(
                    username=username,
                    password_hash=M.hasher.hash(f"pw-{username}-123"),
                    role=role,
                )
                db.add(u)
                db.flush()
                users[username] = u.id
                if grant_flags is not None:
                    db.add(
                        DeviceGrant(
                            device_id=did,
                            user_id=u.id,
                            can_control=grant_flags[0],
                            can_configure=grant_flags[1],
                        )
                    )
            db.commit()

        headers = {}
        tokens = {}
        for username in users:
            res = client.post(
                "/auth/login",
                json={"username": username, "password": f"pw-{username}-123"},
            )
            assert res.status_code == 200
            tok = res.json()["access_token"]
            tokens[username] = tok
            headers[username] = {"Authorization": f"Bearer {tok}"}

        try:
            yield client, headers, tokens, users, did, published
        finally:
            M.app.state.mqtt_receiver = None


def test_s1_jwt_missing_malformed_wrong_signature_wrong_alg_and_claims(sec_api):
    client, _, _, users, did, _ = sec_api
    admin_id = users["sec_admin"]

    protected = [
        ("GET", "/auth/me"),
        ("GET", "/devices"),
        ("GET", f"/devices/{did}"),
        ("GET", "/users"),
        ("GET", "/audit-logs"),
        ("GET", "/alerts"),
        ("GET", "/parking/overview"),
        ("GET", "/telemetry/latest"),
    ]
    for method, path in protected:
        res = client.request(method, path)
        assert res.status_code in (401, 403), f"{method} {path} must reject unauthenticated call"

    wrong_secret_tok = jwt.encode(
        {"sub": str(admin_id), "ver": 0, "exp": M.now() + timedelta(minutes=30)},
        "wrong-secret-key-at-least-32-bytes-long!!",
        algorithm="HS256",
    )
    none_alg_tok = jwt.encode(
        {"sub": str(admin_id), "ver": 0, "exp": M.now() + timedelta(minutes=30)},
        "",
        algorithm="none",
    )
    missing_sub_tok = jwt.encode(
        {"ver": 0, "exp": M.now() + timedelta(minutes=30)},
        M.SECRET,
        algorithm="HS256",
    )
    non_int_sub_tok = jwt.encode(
        {"sub": "sec_admin", "ver": 0, "exp": M.now() + timedelta(minutes=30)},
        M.SECRET,
        algorithm="HS256",
    )
    missing_user_tok = jwt.encode(
        {"sub": "999999", "ver": 0, "exp": M.now() + timedelta(minutes=30)},
        M.SECRET,
        algorithm="HS256",
    )
    wrong_ver_tok = jwt.encode(
        {"sub": str(admin_id), "ver": 99, "exp": M.now() + timedelta(minutes=30)},
        M.SECRET,
        algorithm="HS256",
    )

    invalid_tokens = [
        "not-a-jwt-token",
        "a.b.c",
        wrong_secret_tok,
        none_alg_tok,
        missing_sub_tok,
        non_int_sub_tok,
        missing_user_tok,
        wrong_ver_tok,
    ]
    for bad_tok in invalid_tokens:
        res = client.get("/auth/me", headers={"Authorization": f"Bearer {bad_tok}"})
        assert res.status_code == 401
        body_text = res.text
        assert M.SECRET not in body_text
        assert "$argon2" not in body_text


def test_s1_jwt_expiration_and_revocation_on_logout_password_deactivate_and_role_change(sec_api):
    client, headers, _, users, _, _ = sec_api
    admin_hdr = headers["sec_admin"]

    expired_tok = jwt.encode(
        {"sub": str(users["sec_admin"]), "ver": 0, "exp": M.now() - timedelta(seconds=5)},
        M.SECRET,
        algorithm="HS256",
    )
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {expired_tok}"}).status_code == 401

    assert client.post(
        "/users",
        headers=admin_hdr,
        json={"username": "lifecycle_user", "password": "initial-password-123", "role": "operator"},
    ).status_code == 201

    tok1 = client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "initial-password-123"},
    ).json()["access_token"]
    hdr1 = {"Authorization": f"Bearer {tok1}"}
    me1 = client.get("/auth/me", headers=hdr1)
    assert me1.status_code == 200
    uid = me1.json()["id"]

    # 1. Logout immediately revokes token
    assert client.post("/auth/logout", headers=hdr1).status_code == 204
    assert client.get("/auth/me", headers=hdr1).status_code == 401

    # 2. Password change immediately revokes token and old password
    tok2 = client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "initial-password-123"},
    ).json()["access_token"]
    hdr2 = {"Authorization": f"Bearer {tok2}"}
    assert client.post(
        "/auth/password",
        headers=hdr2,
        json={"old_password": "initial-password-123", "new_password": "updated-password-456"},
    ).status_code == 204
    assert client.get("/auth/me", headers=hdr2).status_code == 401
    assert client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "initial-password-123"},
    ).status_code == 401

    # 3. Role change by admin immediately revokes existing token
    tok3 = client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "updated-password-456"},
    ).json()["access_token"]
    hdr3 = {"Authorization": f"Bearer {tok3}"}
    assert client.get("/devices", headers=hdr3).status_code == 200
    assert client.patch(
        f"/users/{uid}",
        headers=admin_hdr,
        json={"role": "viewer", "active": True},
    ).status_code == 200
    assert client.get("/auth/me", headers=hdr3).status_code == 401
    assert client.get("/devices", headers=hdr3).status_code == 401

    # 4. Deactivation by admin immediately revokes existing token and blocks future logins
    tok4 = client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "updated-password-456"},
    ).json()["access_token"]
    hdr4 = {"Authorization": f"Bearer {tok4}"}
    assert client.get("/auth/me", headers=hdr4).status_code == 200
    assert client.patch(
        f"/users/{uid}",
        headers=admin_hdr,
        json={"role": "viewer", "active": False},
    ).status_code == 200
    assert client.get("/auth/me", headers=hdr4).status_code == 401
    assert client.post(
        "/auth/login",
        json={"username": "lifecycle_user", "password": "updated-password-456"},
    ).status_code == 401


def test_s2_viewer_rbac_restrictions_and_grant_scope(sec_api):
    client, headers, _, users, did, _ = sec_api
    viewer_hdr = headers["sec_viewer"]
    stranger_viewer_hdr = headers["sec_viewer_stranger"]

    # Allowed for viewer: /auth/me and scoped /parking/overview
    assert client.get("/auth/me", headers=viewer_hdr).status_code == 200
    overview_granted = client.get("/parking/overview", headers=viewer_hdr)
    assert overview_granted.status_code == 200 and overview_granted.json()["capacity"] == 2
    overview_ungranted = client.get("/parking/overview", headers=stranger_viewer_hdr)
    assert overview_ungranted.status_code == 200 and overview_ungranted.json()["capacity"] == 0

    # Even if a viewer DB grant row has can_control/can_configure True, viewer is still blocked
    with M.Sessions() as db:
        grant = db.get(DeviceGrant, (did, users["sec_viewer"]))
        grant.can_control = True
        grant.can_configure = True
        db.commit()

    forbidden_calls = [
        ("GET", "/devices", None),
        ("POST", "/devices", {"code": "v_node", "name": "Viewer Node"}),
        ("GET", f"/devices/{did}", None),
        ("PATCH", f"/devices/{did}", {"status": "maintenance"}),
        ("PATCH", f"/devices/{did}/metadata", {"location": "B1"}),
        ("GET", f"/devices/{did}/permissions", None),
        ("POST", f"/devices/{did}/provision", None),
        ("POST", f"/devices/{did}/credentials/rotate", None),
        ("PUT", f"/devices/{did}/slot", {"slot": "P1"}),
        ("GET", f"/devices/{did}/rules", None),
        ("PUT", f"/devices/{did}/rules", {"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 10}),
        ("GET", f"/devices/{did}/configuration", None),
        ("POST", f"/devices/{did}/commands", {"action": "ping"}),
        ("GET", f"/devices/{did}/gates", None),
        ("PUT", f"/devices/{did}/grants/{users['sec_viewer']}", {"can_control": True, "can_configure": True}),
        ("DELETE", f"/devices/{did}/grants/{users['sec_viewer']}", None),
        ("GET", "/telemetry/latest", None),
        ("GET", "/telemetry", None),
        ("GET", "/telemetry/statistics", None),
        ("GET", "/telemetry/export.csv", None),
        ("GET", "/parking/slots", None),
        ("GET", "/dashboard", None),
        ("GET", "/parking/events", None),
        ("GET", "/parking/utilization", None),
        ("GET", "/alerts", None),
        ("POST", "/alerts/1/acknowledge", None),
        ("GET", "/users", None),
        ("POST", "/users", {"username": "v_created", "password": "password123", "role": "viewer"}),
        ("PATCH", f"/users/{users['sec_viewer']}", {"role": "admin", "active": True}),
        ("GET", "/audit-logs", None),
        ("GET", "/storage/policy", None),
    ]
    for method, path, payload in forbidden_calls:
        res = client.request(method, path, headers=viewer_hdr, json=payload)
        assert res.status_code == 403, f"Viewer must get 403 on {method} {path}, got {res.status_code}"


def test_s2_operator_rbac_and_granular_device_grants_anti_idor(sec_api):
    client, headers, _, users, did, _ = sec_api
    op_full = headers["sec_op_full"]
    op_read = headers["sec_op_read"]
    op_ctrl = headers["sec_op_ctrl"]
    op_cfg = headers["sec_op_cfg"]
    op_stranger = headers["sec_op_stranger"]
    admin_hdr = headers["sec_admin"]

    persist_reading(sample_reading(0, 0, boot_id="b0011234", seq=1), M.now())
    runtime_tick()
    runtime_tick()
    alerts = client.get("/alerts?active_only=true", headers=admin_hdr).json()
    aid = [a["id"] for a in alerts if a["kind"] == "parking_full"][0]

    # 1. Operator is blocked (403) from all Admin-only endpoints
    admin_only_calls = [
        ("GET", "/users", None),
        ("POST", "/users", {"username": "op_created", "password": "password123", "role": "viewer"}),
        ("PATCH", f"/users/{users['sec_viewer']}", {"role": "operator", "active": True}),
        ("POST", "/devices", {"code": "op_node", "name": "Op Node"}),
        ("PATCH", f"/devices/{did}", {"status": "maintenance"}),
        ("PATCH", f"/devices/{did}/metadata", {"location": "Gate A"}),
        ("PUT", f"/devices/{did}/grants/{users['sec_op_stranger']}", {"can_control": False, "can_configure": False}),
        ("DELETE", f"/devices/{did}/grants/{users['sec_viewer']}", None),
        ("POST", f"/devices/{did}/provision", None),
        ("POST", f"/devices/{did}/credentials/rotate", None),
        ("PUT", f"/devices/{did}/slot", {"slot": "P1"}),
        ("POST", f"/devices/{did}/commands", {"action": "gate_mode", "gate": "entrance", "mode": "manual"}),
        ("POST", f"/devices/{did}/commands", {"action": "gate", "gate": "entrance", "target": "open"}),
        ("GET", "/audit-logs", None),
        ("GET", "/storage/policy", None),
        ("GET", "/telemetry/latest?device_id=simulator", None),
    ]
    for method, path, payload in admin_only_calls:
        res = client.request(method, path, headers=op_full, json=payload)
        score = res.status_code
        if path.endswith("simulator"):
            assert score == 404
        else:
            assert score == 403, f"Operator must get 403 on {method} {path}, got {score}"

    # 2. Anti-IDOR: Operator without grant receives 404 identical to missing resource
    scoped_get_paths = [
        f"/devices/{did}",
        f"/devices/{did}/permissions",
        f"/devices/{did}/rules",
        f"/devices/{did}/configuration",
        f"/devices/{did}/gates",
        "/telemetry/latest?device_id=esp32_01",
        "/telemetry?device_id=esp32_01",
        "/telemetry/statistics?device_id=esp32_01",
        "/telemetry/export.csv?device_id=esp32_01",
    ]
    for path in scoped_get_paths:
        res = client.get(path, headers=op_stranger)
        assert res.status_code == 404, f"Ungranted operator must get 404 on {path}, got {res.status_code}"
    assert client.get(f"/devices/{did}", headers=op_stranger).json() == client.get("/devices/999999", headers=op_stranger).json()

    out_ack = client.post(f"/alerts/{aid}/acknowledge", headers=op_stranger)
    miss_ack = client.post("/alerts/999999/acknowledge", headers=op_stranger)
    assert out_ack.status_code == miss_ack.status_code == 404
    assert out_ack.json() == miss_ack.json()

    # 3. Granular operator flags (can_control vs can_configure)
    rule_payload = {"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 12}
    ping_payload = {"action": "ping"}
    cfg_payload = {"action": "configure", "report_interval_ms": 2000}

    # Read-only operator
    assert client.get(f"/devices/{did}", headers=op_read).status_code == 200
    assert client.get(f"/devices/{did}/rules", headers=op_read).status_code == 200
    assert client.post(f"/devices/{did}/commands", headers=op_read, json=ping_payload).status_code == 403
    assert client.post(f"/devices/{did}/commands", headers=op_read, json=cfg_payload).status_code == 403
    assert client.put(f"/devices/{did}/rules", headers=op_read, json=rule_payload).status_code == 403

    # Control-only operator
    assert client.post(f"/devices/{did}/commands", headers=op_ctrl, json=ping_payload).status_code == 202
    assert client.post(f"/devices/{did}/commands", headers=op_ctrl, json=cfg_payload).status_code == 403
    assert client.put(f"/devices/{did}/rules", headers=op_ctrl, json=rule_payload).status_code == 403

    # Configure-only operator
    assert client.post(f"/devices/{did}/commands", headers=op_cfg, json=ping_payload).status_code == 403
    assert client.post(f"/devices/{did}/commands", headers=op_cfg, json=cfg_payload).status_code == 202
    assert client.put(f"/devices/{did}/rules", headers=op_cfg, json=rule_payload).status_code == 200


def test_s2_audit_logs_endpoint_access_and_validation(sec_api):
    client, headers, _, _, _, _ = sec_api
    assert client.get("/audit-logs").status_code in (401, 403)
    assert client.get("/audit-logs", headers=headers["sec_viewer"]).status_code == 403
    assert client.get("/audit-logs", headers=headers["sec_op_full"]).status_code == 403
    assert client.get("/audit-logs?limit=0", headers=headers["sec_admin"]).status_code == 422
    assert client.get("/audit-logs?limit=201", headers=headers["sec_admin"]).status_code == 422

    res = client.get("/audit-logs?limit=5", headers=headers["sec_admin"])
    assert res.status_code == 200
    rows = res.json()
    assert 1 <= len(rows) <= 5
    ids = [r["id"] for r in rows]
    assert ids == sorted(ids, reverse=True)
    for row in rows:
        assert set(row.keys()) == {"id", "actor_id", "action", "created_at"}


def test_s3_complete_audit_trail_for_critical_actions(sec_api):
    client, headers, _, users, did, _ = sec_api
    admin_hdr = headers["sec_admin"]
    op_hdr = headers["sec_op_full"]
    admin_id = users["sec_admin"]
    op_id = users["sec_op_full"]

    # 1. Failed login on existing user -> auth.login_failed
    assert client.post(
        "/auth/login",
        json={"username": "sec_op_full", "password": "wrong-password"},
    ).status_code == 401

    # 2. Failed password change -> auth.password_change_failed
    assert client.post(
        "/auth/password",
        headers=op_hdr,
        json={"old_password": "wrong-old-password", "new_password": "new-password-789"},
    ).status_code == 400

    # 3. Create user & update user -> users.create, users.update
    u_res = client.post(
        "/users",
        headers=admin_hdr,
        json={"username": "audited_user", "password": "audited-user-pw", "role": "operator"},
    )
    assert u_res.status_code == 201
    new_uid = u_res.json()["id"]
    assert client.patch(
        f"/users/{new_uid}",
        headers=admin_hdr,
        json={"role": "viewer", "active": True},
    ).status_code == 200

    # 4. Device onboarding, provision, rotate, metadata, grant, ungrant, slot, rules, status
    d_res = client.post(
        "/devices",
        headers=admin_hdr,
        json={"code": "esp32_sec", "name": "Security Node"},
    )
    assert d_res.status_code == 201
    new_did = d_res.json()["id"]

    prov_res = client.post(f"/devices/{new_did}/provision", headers=admin_hdr)
    assert prov_res.status_code == 200
    mqtt_pw_1 = prov_res.json()["mqtt_password"]

    rot_res = client.post(f"/devices/{new_did}/credentials/rotate", headers=admin_hdr)
    assert rot_res.status_code == 200
    mqtt_pw_2 = rot_res.json()["mqtt_password"]

    assert client.patch(
        f"/devices/{new_did}",
        headers=admin_hdr,
        json={"status": "active"},
    ).status_code == 200

    assert client.patch(
        f"/devices/{new_did}/metadata",
        headers=admin_hdr,
        json={"location": "Zone B", "fault": "None"},
    ).status_code == 200

    assert client.put(
        f"/devices/{new_did}/grants/{new_uid}",
        headers=admin_hdr,
        json={"can_control": False, "can_configure": False},
    ).status_code == 200

    assert client.delete(
        f"/devices/{new_did}/grants/{new_uid}",
        headers=admin_hdr,
    ).status_code == 204

    assert client.put(
        f"/devices/{new_did}/slot",
        headers=admin_hdr,
        json={"slot": "P2"},
    ).status_code == 200
    # Restore P2 to esp32_01 so physical slot mapping remains standard
    assert client.put(
        f"/devices/{did}/slot",
        headers=admin_hdr,
        json={"slot": "P2"},
    ).status_code == 200

    assert client.put(
        f"/devices/{did}/rules",
        headers=op_hdr,
        json={"offline_enabled": True, "full_enabled": True, "offline_timeout_s": 15},
    ).status_code == 200

    # 5. Command creation -> commands.create
    persist_reading(sample_reading(0, 0, boot_id="b0019999", seq=1), M.now())
    cmd_res = client.post(
        f"/devices/{did}/commands",
        headers=op_hdr,
        json={"action": "ping", "idempotency_key": "audit-ping-1"},
    )
    assert cmd_res.status_code == 202
    cid = cmd_res.json()["id"]

    # 6. Alert acknowledgement -> alerts.acknowledge
    runtime_tick()
    runtime_tick()
    aid = [a["id"] for a in client.get("/alerts?active_only=true", headers=admin_hdr).json() if a["kind"] == "parking_full"][0]
    assert client.post(f"/alerts/{aid}/acknowledge", headers=op_hdr).status_code == 200

    # 7. Telemetry CSV export -> telemetry.export_csv
    assert client.get("/telemetry/export.csv?device_id=esp32_01", headers=op_hdr).status_code == 200

    # 8. Password change & logout on new user
    u_tok = client.post(
        "/auth/login",
        json={"username": "audited_user", "password": "audited-user-pw"},
    ).json()["access_token"]
    u_hdr = {"Authorization": f"Bearer {u_tok}"}
    assert client.post(
        "/auth/password",
        headers=u_hdr,
        json={"old_password": "audited-user-pw", "new_password": "audited-user-pw-new"},
    ).status_code == 204
    u_tok2 = client.post(
        "/auth/login",
        json={"username": "audited_user", "password": "audited-user-pw-new"},
    ).json()["access_token"]
    assert client.post("/auth/logout", headers={"Authorization": f"Bearer {u_tok2}"}).status_code == 204

    logs = client.get("/audit-logs?limit=200", headers=admin_hdr).json()
    pairs = {(row["actor_id"], row["action"]) for row in logs}

    expected_pairs = {
        (op_id, "auth.login"),
        (op_id, "auth.login_failed"),
        (op_id, "auth.password_change_failed"),
        (admin_id, "users.create:audited_user"),
        (admin_id, f"users.update:{new_uid}"),
        (admin_id, "devices.create:esp32_sec"),
        (admin_id, f"devices.provision:{new_did}"),
        (admin_id, f"devices.rotate_credentials:{new_did}"),
        (admin_id, f"devices.status:{new_did}:active"),
        (admin_id, f"devices.metadata:{new_did}"),
        (admin_id, f"devices.grant:{new_did}:user:{new_uid}"),
        (admin_id, f"devices.ungrant:{new_did}:user:{new_uid}"),
        (admin_id, f"devices.assign_slot:{new_did}:P2"),
        (op_id, f"devices.rules:{did}"),
        (op_id, f"commands.create:{did}:{cid}:ping"),
        (op_id, f"alerts.acknowledge:{aid}:device:{did}"),
        (op_id, "telemetry.export_csv:esp32_01"),
        (new_uid, "auth.password_changed"),
        (new_uid, "auth.logout"),
    }
    assert expected_pairs.issubset(pairs)

    # Verify zero secret leakage in audit logs
    serialized_logs = str(logs)
    for secret_value in (
        "pw-sec_admin-123",
        "pw-sec_op_full-123",
        "wrong-password",
        "wrong-old-password",
        "audited-user-pw",
        "audited-user-pw-new",
        mqtt_pw_1,
        mqtt_pw_2,
        u_tok,
        u_tok2,
        "$argon2",
    ):
        assert secret_value not in serialized_logs


def test_s3_idempotency_noop_and_failed_actions_do_not_duplicate_or_pollute_audit(sec_api):
    client, headers, _, users, did, _ = sec_api
    admin_hdr = headers["sec_admin"]
    op_hdr = headers["sec_op_full"]

    persist_reading(sample_reading(0, 0, boot_id="b0017777", seq=1), M.now())
    runtime_tick()
    runtime_tick()
    aid = [a["id"] for a in client.get("/alerts?active_only=true", headers=admin_hdr).json() if a["kind"] == "parking_full"][0]

    # 1. Idempotent alert acknowledge writes only 1 audit log
    assert client.post(f"/alerts/{aid}/acknowledge", headers=op_hdr).status_code == 200
    assert client.post(f"/alerts/{aid}/acknowledge", headers=admin_hdr).status_code == 200
    logs = client.get("/audit-logs?limit=200", headers=admin_hdr).json()
    ack_entries = [r for r in logs if r["action"] == f"alerts.acknowledge:{aid}:device:{did}"]
    assert len(ack_entries) == 1

    # 2. Idempotent command creation writes only 1 audit log
    cmd_body = {"action": "ping", "idempotency_key": "idem-ping-key"}
    r1 = client.post(f"/devices/{did}/commands", headers=op_hdr, json=cmd_body)
    r2 = client.post(f"/devices/{did}/commands", headers=op_hdr, json=cmd_body)
    assert r1.status_code == 202 and r2.status_code == 202
    cid = r1.json()["id"]
    logs = client.get("/audit-logs?limit=200", headers=admin_hdr).json()
    cmd_entries = [r for r in logs if r["action"] == f"commands.create:{did}:{cid}:ping"]
    assert len(cmd_entries) == 1

    # 3. No-op device status PATCH (already active -> active) does not write duplicate status audit log
    before_status_logs = [
        r for r in client.get("/audit-logs?limit=200", headers=admin_hdr).json()
        if r["action"] == f"devices.status:{did}:active"
    ]
    assert client.patch(f"/devices/{did}", headers=admin_hdr, json={"status": "active"}).status_code == 200
    after_status_logs = [
        r for r in client.get("/audit-logs?limit=200", headers=admin_hdr).json()
        if r["action"] == f"devices.status:{did}:active"
    ]
    assert len(after_status_logs) == len(before_status_logs)

    # 4. Failed operations do NOT create false positive audit records
    snapshot_ids = [r["id"] for r in client.get("/audit-logs?limit=200", headers=admin_hdr).json()]

    # Unknown username login (no user in DB)
    assert client.post("/auth/login", json={"username": "nonexistent_ghost", "password": "bad-password-123"}).status_code == 401
    # Duplicate username (409)
    assert client.post("/users", headers=admin_hdr, json={"username": "sec_admin", "password": "password123", "role": "admin"}).status_code == 409
    # Self-demotion / self-disable (400)
    assert client.patch(f"/users/{users['sec_admin']}", headers=admin_hdr, json={"role": "operator", "active": False}).status_code == 400
    # Duplicate device code (409)
    assert client.post("/devices", headers=admin_hdr, json={"code": "esp32_01", "name": "Dup"}).status_code == 409
    # Invalid lifecycle transition: active -> registered (409)
    assert client.patch(f"/devices/{did}", headers=admin_hdr, json={"status": "registered"}).status_code == 409
    # Invalid export limit (422) and ungranted export (404)
    assert client.get("/telemetry/export.csv?limit=0", headers=op_hdr).status_code == 422
    assert client.get("/telemetry/export.csv", headers=headers["sec_op_stranger"]).status_code == 404
    # Broker failure during credential rotation (503)
    def fail_broker(*args):
        raise BrokerUnavailable("simulated broker outage")
    orig_broker = M.app.state.broker_admin
    M.app.state.broker_admin = SimpleNamespace(rotate_password=fail_broker, set_enabled=fail_broker)
    try:
        assert client.post(f"/devices/{did}/credentials/rotate", headers=admin_hdr).status_code == 503
        assert client.patch(f"/devices/{did}", headers=admin_hdr, json={"status": "revoked"}).status_code == 503
    finally:
        M.app.state.broker_admin = orig_broker

    after_failed_ids = [r["id"] for r in client.get("/audit-logs?limit=200", headers=admin_hdr).json()]
    assert after_failed_ids == snapshot_ids


def test_s4_security_regression_e1_e2_alerts_and_device_lifecycle(sec_api, fake_broker, monkeypatch):
    client, headers, _, users, did, _ = sec_api
    admin_hdr = headers["sec_admin"]
    op_hdr = headers["sec_op_full"]
    assert client.put(f"/devices/{did}/rules", headers=admin_hdr, json={
        "offline_enabled": True, "full_enabled": True, "offline_timeout_s": 10,
    }).status_code == 200

    # 1. Trigger parking_full and acknowledge (E1)
    t0 = M.now()
    persist_reading(sample_reading(0, 0, boot_id="b001abcd", seq=1), t0)
    runtime_tick()
    runtime_tick()
    active_alerts = client.get("/alerts?active_only=true", headers=op_hdr).json()
    full_alerts = [a for a in active_alerts if a["kind"] == "parking_full"]
    assert len(full_alerts) == 1
    full_id = full_alerts[0]["id"]
    ack_res = client.post(f"/alerts/{full_id}/acknowledge", headers=op_hdr)
    assert ack_res.status_code == 200
    assert ack_res.json()["acknowledged"] is True and ack_res.json()["active"] is True

    # 2. Trigger device_offline (E2) after timeout, acknowledge while active, then recover via new telemetry
    t1 = t0 + timedelta(seconds=25)
    monkeypatch.setattr(M, "now", lambda: t1)
    runtime_tick()
    runtime_tick()
    active_alerts = client.get("/alerts?active_only=true", headers=op_hdr).json()
    offline_alerts = [a for a in active_alerts if a["kind"] == "device_offline"]
    assert len(offline_alerts) == 1
    off_id = offline_alerts[0]["id"]

    off_ack = client.post(f"/alerts/{off_id}/acknowledge", headers=op_hdr)
    assert off_ack.status_code == 200
    assert off_ack.json()["acknowledged"] is True
    assert off_ack.json()["acknowledged_by"] == users["sec_op_full"]
    assert off_ack.json()["active"] is True

    # Recovery reading resolves both device_offline and parking_full (since slots are now 1, 1 = available)
    t2 = t1 + timedelta(seconds=2)
    monkeypatch.setattr(M, "now", lambda: t2)
    persist_reading(sample_reading(1, 1, boot_id="b001abcd", seq=2), t2)
    runtime_tick()
    all_alerts = {a["id"]: a for a in client.get("/alerts", headers=op_hdr).json()}
    assert all_alerts[full_id]["active"] is False and all_alerts[full_id]["acknowledged"] is True
    assert all_alerts[off_id]["active"] is False and all_alerts[off_id]["acknowledged"] is True

    # 3. Device lifecycle revocation disables broker credentials and cancels pending commands
    cmd = client.post(f"/devices/{did}/commands", headers=op_hdr, json={"action": "ping"}).json()
    assert client.patch(f"/devices/{did}", headers=admin_hdr, json={"status": "revoked"}).status_code == 200
    assert fake_broker.clients["esp32_01"]["enabled"] is False
    assert client.get(f"/commands/{cmd['id']}", headers=op_hdr).json()["status"] == "cancelled"
