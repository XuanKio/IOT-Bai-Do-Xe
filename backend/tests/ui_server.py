r"""Isolated browser-QA server. Never opens the real database or MQTT broker.

Run from the repository root:
    backend\.venv\Scripts\python.exe backend\tests\ui_server.py --port 8765

All accounts and readings are disposable test fixtures, not production data.
"""
import argparse
import asyncio
from collections import deque
from contextlib import asynccontextmanager
from datetime import timedelta
import os
from pathlib import Path
import sys
import tempfile
import time

TEMP = tempfile.TemporaryDirectory(prefix="parkflow-ui-test-")
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(TEMP.name) / "ui-test.db")
os.environ["JWT_SECRET"] = "isolated-browser-tests-not-a-production-secret"
os.environ["MQTT_ENABLED"] = "0"
os.environ["BACKGROUND_ENABLED"] = "1"
os.environ.pop("MQTT_ADMIN_PASSWORD", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select
import uvicorn
from app import main as M
from app.domain import AlertDetails, DeviceDetails, DeviceGrant
from app.domain_service import acknowledge_command, details, persist_reading, receive_status, seed_physical
from app.mqtt_receiver import AckMessage, StatusMessage, TelemetryMessage

PASSWORD = "frontend-tests-only"
BOOT = "1234567890abcdef"
pending = deque()
scenario = {"online": True, "full": False, "ack_enabled": True, "interval": 1000, "entrance": False, "exit": False}
sequence = 0
gate_states = {name: {"mode": "auto", "target": "closed", "revision": 0, "due": None}
               for name in ("entrance", "exit")}


def gate_snapshot():
    now = time.monotonic()
    readings = {}
    for name, gpio in (("entrance", 16), ("exit", 19)):
        state = gate_states[name]
        if state["mode"] == "auto":
            if scenario[name]:
                state["target"], state["due"] = "open", None
            elif state["target"] == "open":
                if state["due"] is None:
                    state["due"] = now + 3
                if now >= state["due"]:
                    state["target"], state["due"] = "closed", None
        readings[name] = {"mode": state["mode"], "target": state["target"], "revision": state["revision"],
            "servo_gpio": gpio, "pwm_ready": True,
            "close_remaining_ms": max(0, min(3000, int((state["due"] - now) * 1000))) if state["due"] else 0}
    return readings


class FixtureBroker:
    def __init__(self):
        self.clients = {"esp32_01": True}

    def provision(self, code, password):
        self.clients[code] = True

    def set_enabled(self, code, enabled):
        self.clients[code] = enabled

    def rotate_password(self, code, password):
        pass


class FixtureReceiver:
    connected = True
    subscribed = True

    def publish_command(self, code, payload):
        pending.append((time.monotonic() + .8, code, payload))

    def stop(self):
        self.connected = False


def reading(stamp, level1=0, level2=1):
    global sequence
    sequence += 1
    return TelemetryMessage(device_id="esp32_01", uptime_s=100000 + sequence,
        do=level1, detected=level1 == 0, do2=level2, detected2=level2 == 0,
        boot_id=BOOT, seq=sequence, firmware="esp32_core-0.4.0",
        hardware="ESP32-D0WD-V3", report_interval_ms=scenario["interval"],
        gate_control=gate_snapshot(), gate_sensors={name: {"gpio": gpio, "do": 0 if scenario[name] else 1,
            "detected": scenario[name]} for name, gpio in (("entrance", 32), ("exit", 33))})


def seed():
    with M.Sessions() as db:
        seed_physical(db)
        device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
        device.name = "ESP32 P1/P2 — kiểm thử mô phỏng"
        info = details(db, device)
        info.location = "Môi trường kiểm thử tách biệt"
        for name, role, granted, control, configure in (
            ("adminqa", "admin", False, False, False),
            ("operatorqa", "operator", True, True, True),
            ("limitedqa", "operator", True, False, False),
            ("viewerqa", "viewer", True, False, False),
            ("observerqa", "viewer", False, False, False),
        ):
            user = M.User(username=name, role=role, password_hash=M.hasher.hash(PASSWORD))
            db.add(user)
            db.flush()
            if granted:
                db.add(DeviceGrant(device_id=device.id, user_id=user.id,
                                   can_control=control, can_configure=configure))
        db.add(M.Device(code="esp32_spare", name="ESP32 dự phòng — kiểm thử", status="registered"))
        for i, kind in enumerate(("device_offline", "parking_full")):
            alert = M.Alert(message="Cảnh báo lịch sử từ dữ liệu kiểm thử",
                            created_at=M.now() - timedelta(minutes=30 + i * 10),
                            acknowledged=i == 1)
            db.add(alert)
            db.flush()
            db.add(AlertDetails(alert_id=alert.id, device_id=device.id, kind=kind,
                                resolved_at=M.now() - timedelta(minutes=20)))
        db.commit()
    for hour in range(23, -1, -1):
        for minute in (48, 36, 24, 12, 0):
            stamp = M.now() - timedelta(hours=hour, minutes=minute)
            persist_reading(reading(stamp, hour % 2, (hour + minute) % 2), stamp)
    # The most recent sample is explicitly simulated by this test-only server.
    persist_reading(reading(M.now()), M.now())


async def producer():
    last_read = 0
    while True:
        with M.Sessions() as db:
            device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
            enabled = device and device.status in {"active", "provisioned", "maintenance"}
        enabled = enabled and M.app.state.broker_admin.clients.get("esp32_01", False)
        if scenario["online"] and enabled and time.monotonic() - last_read >= scenario["interval"] / 1000:
            persist_reading(reading(M.now(), 0, 0 if scenario["full"] else 1), M.now())
            last_read = time.monotonic()
        while pending and pending[0][0] <= time.monotonic():
            _, code, command = pending.popleft()
            if not scenario["ack_enabled"] or not scenario["online"] or not enabled:
                continue
            if command["action"] == "configure":
                scenario["interval"] = command["arguments"]["report_interval_ms"]
            result = {"report_interval_ms": scenario["interval"], "uptime_s": 100000 + sequence}
            success, error = True, None
            if command["action"] in {"gate", "gate_mode"}:
                args = command["arguments"]
                state = gate_states[args["gate"]]
                success = args["revision"] > state["revision"]
                if command["action"] == "gate":
                    success = success and state["mode"] == "manual"
                if success:
                    state["revision"] = args["revision"]
                    state["due"] = None
                    if command["action"] == "gate_mode":
                        state["mode"] = args["mode"]
                    else:
                        state["target"] = args["target"]
                    gate_snapshot()
                else:
                    error = "Invalid gate command"
                result.update({"gate": args["gate"], "revision": state["revision"], "mode": state["mode"],
                    "target": state["target"], "pwm_ready": True})
            acknowledge_command(AckMessage(device_id=code, command_id=command["command_id"], boot_id=BOOT,
                status="succeeded" if success else "failed", error=error, result=result), M.now())
        await asyncio.sleep(.2)


original_lifespan = M.app.router.lifespan_context


@asynccontextmanager
async def fixture_lifespan(app):
    async with original_lifespan(app):
        app.state.mqtt_receiver = FixtureReceiver()
        app.state.broker_admin = FixtureBroker()
        seed()
        task = asyncio.create_task(producer())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


M.app.router.lifespan_context = fixture_lifespan


class Scenario(BaseModel):
    online: bool | None = None
    full: bool | None = None
    ack_enabled: bool | None = None
    entrance: bool | None = None
    exit: bool | None = None


@M.app.post("/__fixture/scenario", include_in_schema=False)
def set_scenario(body: Scenario, user=Depends(M.roles("admin"))):
    scenario.update(body.model_dump(exclude_none=True))
    if body.online is False:
        receive_status(StatusMessage(device_id="esp32_01", state="offline", boot_id=BOOT), M.now())
    return scenario


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        uvicorn.run(M.app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        M.engine.dispose()
        TEMP.cleanup()
