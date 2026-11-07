import os
import secrets
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from contextlib import asynccontextmanager
from app.coordination import serialized


def now():
    return datetime.now(timezone.utc)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./parking.db")
SECRET = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {})
Sessions = sessionmaker(engine, expire_on_commit=False)
hasher = PasswordHash.recommended()
bearer = HTTPBearer()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="viewer")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="registered")
    firmware: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Slot(Base):
    __tablename__ = "slots"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    occupied: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    message: Mapped[str] = mapped_column(String(500))
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Telemetry(Base):
    __tablename__ = "sensor_telemetry"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_code: Mapped[str] = mapped_column(String(64), index=True)
    uptime_s: Mapped[int] = mapped_column(Integer)
    do_level: Mapped[int] = mapped_column(Integer)
    detected: Mapped[bool] = mapped_column(Boolean)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class TelemetrySlot(Base):
    __tablename__ = "sensor_slot_readings"
    telemetry_id: Mapped[int] = mapped_column(ForeignKey("sensor_telemetry.id"), primary_key=True)
    slot_name: Mapped[str] = mapped_column(String(32), primary_key=True)
    do_level: Mapped[int] = mapped_column(Integer)
    occupied: Mapped[bool] = mapped_column(Boolean)


from app.domain import DeviceDetails, DeviceGrant, DeviceSlot, AlertDetails, LiveTelemetry


def store_reading(item, received_at):
    from app.domain_service import persist_reading
    return persist_reading(item, received_at)


async def background_monitor():
    from app.domain_service import runtime_tick
    while True:
        try:
            await asyncio.to_thread(runtime_tick)
        except Exception:
            logging.getLogger(__name__).exception("Background monitor tick failed")
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    with Sessions() as db:
        for name in ("P1", "P2"):
            if not db.scalar(select(Slot).where(Slot.name == name)):
                db.add(Slot(name=name, occupied=None))
        db.flush()
        if os.getenv("MQTT_ENABLED", "0") == "1":
            from app.domain_service import seed_physical
            seed_physical(db)
        db.commit()
    app.state.mqtt_receiver = None
    app.state.broker_admin = None
    discovery = None
    if os.getenv("MQTT_ADMIN_PASSWORD"):
        from app.broker_admin import BrokerAdmin
        app.state.broker_admin = BrokerAdmin()
    if os.getenv("MQTT_ENABLED", "0") == "1":
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        from app.mqtt_receiver import MqttReceiver
        from app.domain_service import acknowledge_command, receive_status
        receiver = MqttReceiver(store_reading, on_ack=acknowledge_command, on_status=receive_status,
                                ack_telemetry=True)
        app.state.mqtt_receiver = receiver
        receiver.start()
        if receiver.host in {"127.0.0.1", "localhost"}:
            from app.broker_discovery import BrokerDiscovery
            discovery = BrokerDiscovery(receiver.port)
            discovery.start()
    monitor = asyncio.create_task(background_monitor()) if os.getenv("BACKGROUND_ENABLED", "1") == "1" else None
    try:
        yield
    finally:
        if discovery:
            await asyncio.to_thread(discovery.stop)
        if monitor:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
        if app.state.mqtt_receiver:
            app.state.mqtt_receiver.stop()


app = FastAPI(title="Parking IoT Backend", version="0.2.0", lifespan=lifespan)


def session():
    with Sessions() as db:
        yield db


def current_user(auth: HTTPAuthorizationCredentials = Depends(bearer), db: Session = Depends(session)):
    try:
        data = jwt.decode(auth.credentials, SECRET, algorithms=["HS256"])
        user = db.get(User, int(data["sub"]))
        if not user or not user.active or data.get("ver") != user.token_version:
            raise ValueError()
        return user
    except (InvalidTokenError, ValueError, KeyError, TypeError):
        raise HTTPException(401, "Invalid or expired token")


def roles(*allowed):
    def check(user: User = Depends(current_user)):
        if user.role not in allowed:
            raise HTTPException(403, "Insufficient permissions")
        return user
    return check


def audit(db, user, action):
    db.add(Audit(actor_id=user.id, action=action))


def public_user(user):
    return {"id": user.id, "username": user.username, "role": user.role, "active": user.active}


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=10, max_length=128)


class UserCreate(Credentials):
    role: Literal["admin", "operator", "viewer"] = "viewer"


class UserUpdate(BaseModel):
    role: Literal["admin", "operator", "viewer"]
    active: bool


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=10, max_length=128)


class DeviceCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")
    name: str = Field(min_length=1, max_length=100)


class DeviceUpdate(BaseModel):
    status: Literal["registered", "provisioned", "active", "maintenance", "revoked", "decommissioned"]


@app.get("/health")
def health():
    receiver = getattr(app.state, "mqtt_receiver", None)
    return {"status": "ok", "hardware_integration": "mqtt_telemetry" if receiver else "not_implemented",
            "mqtt_connected": bool(receiver and receiver.connected),
            "mqtt_subscribed": bool(receiver and receiver.subscribed)}


def telemetry_view(item, receiver, db):
    stamp = item.received_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = max(0, (now() - stamp).total_seconds())
    from app.domain_service import connectivity
    device = db.scalar(select(Device).where(Device.code == item.device_code))
    info = db.get(DeviceDetails, device.id) if device else None
    timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 5
    connected = connectivity(device, info) == "online" if device else bool(receiver and receiver.connected and receiver.subscribed)
    samples = list(db.scalars(select(TelemetrySlot).where(TelemetrySlot.telemetry_id == item.id)
                             .order_by(TelemetrySlot.slot_name)))
    slot_values = [{"name": sample.slot_name, "gpio": 27 if sample.slot_name == "P1" else 26,
                    "do": sample.do_level, "occupied": sample.occupied} for sample in samples]
    return {"id": item.id, "device_id": item.device_code, "uptime_s": item.uptime_s,
            "do": item.do_level, "detected": item.detected, "received_at": stamp.isoformat(),
            "slots": slot_values,
            "simulated": item.device_code == "simulator",
            "fresh": bool(connected and age < timeout)}


@app.get("/telemetry/latest")
def latest_telemetry(device_id: str = "esp32_01", user: User = Depends(roles("admin", "operator")),
                     db: Session = Depends(session)):
    from app.domain_service import authorize
    if device_id != "simulator" or user.role != "admin":
        authorize(db, user, code=device_id)
    live = db.get(LiveTelemetry, device_id)
    if live:
        from app.storage import live_view, gate_sensor_view
        from app.domain_service import connectivity, utc
        device = db.scalar(select(Device).where(Device.code == device_id))
        info = db.get(DeviceDetails, device.id) if device else None
        fresh = (device and device.status == "active" and connectivity(device, info) == "online"
                 and live.invalidated_at is None and utc(live.received_at) <= now() < utc(live.expires_at))
        result = live_view(live, fresh)
        result["gate_sensors"] = gate_sensor_view(db, live, fresh)
        return result
    item = db.scalar(select(Telemetry).where(Telemetry.device_code == device_id)
                     .order_by(Telemetry.id.desc()).limit(1))
    return telemetry_view(item, getattr(app.state, "mqtt_receiver", None), db) if item else None


@app.get("/telemetry")
def telemetry_history(device_id: str = "esp32_01", limit: int = 50, before_id: int | None = None,
                      from_at: datetime | None = None, to_at: datetime | None = None,
                      user: User = Depends(roles("admin", "operator")), db: Session = Depends(session)):
    from app.domain_service import authorize
    from app.management import time_filter
    if device_id != "simulator" or user.role != "admin":
        authorize(db, user, code=device_id)
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    receiver = getattr(app.state, "mqtt_receiver", None)
    query = time_filter(select(Telemetry).where(Telemetry.device_code == device_id),
                        Telemetry.received_at, from_at, to_at)
    if before_id is not None:
        query = query.where(Telemetry.id < before_id)
    items = db.scalars(query.order_by(Telemetry.id.desc()).limit(limit))
    return [telemetry_view(item, receiver, db) for item in items]


@app.post("/auth/login")
def login(body: Credentials, db: Session = Depends(session)):
    user = db.scalar(select(User).where(User.username == body.username))
    if not user or not user.active or not hasher.verify(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    token = jwt.encode({"sub": str(user.id), "ver": user.token_version, "exp": now() + timedelta(minutes=int(os.getenv("TOKEN_MINUTES", "60")))}, SECRET, algorithm="HS256")
    return {"access_token": token, "token_type": "bearer"}


@app.get("/auth/me")
def me(user: User = Depends(current_user)):
    return public_user(user)


@app.post("/auth/logout", status_code=204)
def logout(user: User = Depends(current_user), db: Session = Depends(session)):
    user.token_version += 1
    audit(db, user, "auth.logout")
    db.commit()


@app.post("/auth/password", status_code=204)
def password(body: PasswordChange, user: User = Depends(current_user), db: Session = Depends(session)):
    if not hasher.verify(body.old_password, user.password_hash):
        raise HTTPException(400, "Incorrect current password")
    user.password_hash = hasher.hash(body.new_password)
    user.token_version += 1
    audit(db, user, "auth.password_changed")
    db.commit()


@app.post("/users", status_code=201)
def create_user(body: UserCreate, user: User = Depends(roles("admin")), db: Session = Depends(session)):
    item = User(username=body.username, password_hash=hasher.hash(body.password), role=body.role)
    db.add(item)
    audit(db, user, "users.create:" + body.username)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Username already exists")
    return public_user(item)


@app.get("/users")
def users(user: User = Depends(roles("admin")), db: Session = Depends(session)):
    return [public_user(u) for u in db.scalars(select(User).order_by(User.id))]


@app.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, user: User = Depends(roles("admin")), db: Session = Depends(session)):
    item = db.get(User, user_id)
    if not item:
        raise HTTPException(404, "User not found")
    if user_id == user.id and (not body.active or body.role != "admin"):
        raise HTTPException(400, "Cannot disable or demote yourself")
    item.role, item.active = body.role, body.active
    item.token_version += 1
    audit(db, user, f"users.update:{user_id}")
    db.commit()
    return public_user(item)


@app.post("/devices", status_code=201)
def create_device(body: DeviceCreate, user: User = Depends(roles("admin")), db: Session = Depends(session)):
    if body.code in {"receiver", "broker_admin", "simulator"}:
        raise HTTPException(422, "Reserved device code")
    item = Device(**body.model_dump())
    db.add(item)
    audit(db, user, "devices.create:" + body.code)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Device code already exists")
    from app.domain_service import details
    details(db, item)
    db.commit()
    return device_view(item, db)


def device_view(item, db):
    from app.domain_service import connectivity, utc
    info = db.get(DeviceDetails, item.id)
    return {"id": item.id, "code": item.code, "name": item.name, "status": item.status,
            "firmware": item.firmware, "connectivity": connectivity(item, info),
            "hardware": info.hardware if info else None, "location": info.location if info else "",
            "last_seen": utc(info.last_seen).isoformat() if info and info.last_seen else None,
            "fault": info.fault if info else None,
            "broker_provisioned": bool(info and info.broker_provisioned),
            "report_interval_ms": info.report_interval_ms if info else 1000,
            "effective_offline_timeout_s": max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 10}


@app.get("/devices")
def devices(user: User = Depends(roles("admin", "operator")), db: Session = Depends(session)):
    from app.domain_service import visible_codes
    codes = visible_codes(db, user)
    query = select(Device)
    if codes is not None:
        query = query.where(Device.code.in_(codes))
    return [device_view(d, db) for d in db.scalars(query.order_by(Device.id))]


@app.patch("/devices/{device_id}")
@serialized
def update_device(device_id: int, body: DeviceUpdate, user: User = Depends(roles("admin")), db: Session = Depends(session)):
    item = db.get(Device, device_id)
    if not item:
        raise HTTPException(404, "Device not found")
    transitions = {"registered": {"provisioned", "revoked", "decommissioned"}, "provisioned": {"active", "revoked", "decommissioned"}, "active": {"maintenance", "revoked", "decommissioned"}, "maintenance": {"active", "revoked", "decommissioned"}, "revoked": {"provisioned", "decommissioned"}, "decommissioned": set()}
    if body.status != item.status and body.status not in transitions[item.status]:
        raise HTTPException(409, "Invalid lifecycle transition")
    from app.domain_service import details
    from app.management import broker_call
    from app.domain import DeviceCommand
    info = details(db, item)
    if body.status != item.status:
        if body.status in {"provisioned", "active"}:
            if not info.broker_provisioned:
                raise HTTPException(409, "Provision device credentials first")
            broker_call("set_enabled", item.code, True)
        elif body.status in {"revoked", "decommissioned"} and info.broker_provisioned:
            broker_call("set_enabled", item.code, False)
            info.forced_offline = True
        if body.status in {"maintenance", "revoked", "decommissioned"}:
            for command in db.scalars(select(DeviceCommand).where(
                    DeviceCommand.device_id == item.id, DeviceCommand.status.in_(["queued", "sent"]))):
                command.status, command.completed_at = "cancelled", now()
                command.error = "Device lifecycle changed"
    if body.status != item.status and body.status != "active":
        from app.storage import invalidate
        invalidate(db, item, now())
    item.status = body.status
    audit(db, user, f"devices.status:{device_id}:{body.status}")
    db.commit()
    return device_view(item, db)


@app.get("/parking/slots")
def slots(user: User = Depends(roles("admin", "operator")), db: Session = Depends(session)):
    return live_slot_views(db, user)


def live_slot_views(db, user=None):
    from app.domain_service import slot_views
    return slot_views(db, user)


@app.get("/dashboard")
def dashboard(user: User = Depends(roles("admin", "operator")), db: Session = Depends(session)):
    items = live_slot_views(db, user)
    return {"capacity": len(items), "occupied": sum(s["occupied"] is True for s in items),
            "available": sum(s["occupied"] is False for s in items),
            "unknown": sum(s["occupied"] is None for s in items), "gate_state": "unknown",
            "hardware_integration": "mqtt_parking_slots" if getattr(app.state, "mqtt_receiver", None) else "not_implemented"}


@app.get("/alerts")
def alerts(limit: int = 50, active_only: bool = False, user: User = Depends(roles("admin", "operator")), db: Session = Depends(session)):
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    from app.management import scoped_alerts
    return scoped_alerts(db, user, limit, active_only)


@app.get("/audit-logs")
def logs(limit: int = 50, user: User = Depends(roles("admin")), db: Session = Depends(session)):
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    return list(db.scalars(select(Audit).order_by(Audit.id.desc()).limit(limit)))


from app.management import router as management_router
app.include_router(management_router)
from app.public_parking import router as parking_router
app.include_router(parking_router)

from app.web import install_frontend
install_frontend(app)
