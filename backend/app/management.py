"""Management APIs for the coursework's user/device/data/monitoring requirements."""
import csv
import io
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from app import main as M
from app.broker_admin import BrokerUnavailable
from app.domain import LiveTelemetry, LiveGateControl, LiveGateSensors, GateCommandCounter, AlertDetails, DeviceCommand, DeviceDetails, DeviceGrant, DeviceSlot, ParkingEvent, HourlyOccupancy
from app.coordination import serialized
from app.domain_service import ALERT_KINDS, authorize, connectivity, details, receiver_ready, utc, visible_codes

router = APIRouter(dependencies=[Depends(M.roles("admin", "operator"))])


def broker_call(method, *arguments):
    broker = getattr(M.app.state, "broker_admin", None)
    if not broker:
        raise HTTPException(503, "Broker administration is not configured")
    try:
        return getattr(broker, method)(*arguments)
    except BrokerUnavailable:
        raise HTTPException(503, "Broker did not confirm the change; retry after checking MQTT")


def time_filter(query, column, from_at, to_at):
    for value in (from_at, to_at):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(422, "Timestamps must include a timezone, e.g. +07:00 or Z")
    if from_at and to_at and from_at > to_at:
        raise HTTPException(422, "from_at must be before to_at")
    if from_at:
        query = query.where(column >= from_at.astimezone(timezone.utc))
    if to_at:
        query = query.where(column <= to_at.astimezone(timezone.utc))
    return query


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GrantBody(StrictBody):
    can_control: bool = False
    can_configure: bool = False


class MetadataBody(StrictBody):
    location: str | None = Field(default=None, max_length=100)
    fault: str | None = Field(default=None, max_length=200)


class AssignSlotBody(StrictBody):
    slot: Literal["P1", "P2"]


class RuleBody(StrictBody):
    offline_enabled: bool = True
    full_enabled: bool = True
    offline_timeout_s: int = Field(default=10, ge=5, le=120)


class CommandBody(StrictBody):
    action: Literal["ping", "configure", "gate", "gate_mode"]
    gate: Literal["entrance", "exit"] | None = None
    target: Literal["open", "closed"] | None = None
    mode: Literal["auto", "manual"] | None = None
    report_interval_ms: int | None = Field(default=None, ge=500, le=10000)
    timeout_s: int = Field(default=15, ge=5, le=60)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")


def command_view(item):
    return {"id": item.id, "device_id": item.device_id, "action": item.action,
            "arguments": item.arguments, "status": item.status, "attempts": item.attempts,
            "created_at": utc(item.created_at).isoformat(), "expires_at": utc(item.expires_at).isoformat(),
            "completed_at": utc(item.completed_at).isoformat() if item.completed_at else None,
            "error": item.error, "result": item.result}


@router.get("/devices/{device_id}")
def get_device(device_id: int, user: M.User = Depends(M.current_user), db=Depends(M.session)):
    return M.device_view(authorize(db, user, device_id=device_id), db)


@router.get("/devices/{device_id}/permissions")
def own_permissions(device_id: int, user: M.User = Depends(M.current_user), db=Depends(M.session)):
    """Expose only the caller's effective rights, never another user's grants."""
    device = authorize(db, user, device_id=device_id)
    grant = db.get(DeviceGrant, (device.id, user.id))
    admin = user.role == "admin"
    operator = user.role == "operator" and grant is not None
    return {"device_id": device.id, "can_read": True, "can_manage": admin,
            "can_control": admin or bool(operator and grant.can_control),
            "can_configure": admin or bool(operator and grant.can_configure)}


@router.patch("/devices/{device_id}/metadata")
def update_metadata(device_id: int, body: MetadataBody, user=Depends(M.roles("admin")), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    info = details(db, device)
    if "location" in body.model_fields_set:
        info.location = body.location or ""
    if "fault" in body.model_fields_set:
        info.fault = body.fault
    M.audit(db, user, f"devices.metadata:{device.id}")
    db.commit()
    return M.device_view(device, db)


@router.put("/devices/{device_id}/grants/{user_id}")
def grant_device(device_id: int, user_id: int, body: GrantBody, user=Depends(M.roles("admin")), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    target = db.get(M.User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    grant = db.get(DeviceGrant, (device.id, user_id))
    if not grant:
        grant = DeviceGrant(device_id=device.id, user_id=user_id)
        db.add(grant)
    grant.can_control, grant.can_configure = body.can_control, body.can_configure
    M.audit(db, user, f"devices.grant:{device.id}:user:{user_id}")
    db.commit()
    return {"device_id": device.id, "user_id": user_id, **body.model_dump()}


@router.get("/devices/{device_id}/grants")
def list_grants(device_id: int, user=Depends(M.roles("admin")), db=Depends(M.session)):
    authorize(db, user, device_id=device_id)
    return [{"user_id": grant.user_id, "can_control": grant.can_control, "can_configure": grant.can_configure}
            for grant in db.scalars(select(DeviceGrant).where(DeviceGrant.device_id == device_id))]


@router.delete("/devices/{device_id}/grants/{user_id}", status_code=204)
def remove_grant(device_id: int, user_id: int, user=Depends(M.roles("admin")), db=Depends(M.session)):
    authorize(db, user, device_id=device_id)
    grant = db.get(DeviceGrant, (device_id, user_id))
    if not grant:
        raise HTTPException(404, "Grant not found")
    db.delete(grant)
    M.audit(db, user, f"devices.ungrant:{device_id}:user:{user_id}")
    db.commit()


@router.post("/devices/{device_id}/provision")
def provision_device(device_id: int, user=Depends(M.roles("admin")), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    info = details(db, device)
    if device.status != "registered" or info.broker_provisioned:
        raise HTTPException(409, "Device already provisioned or not in registered state")
    password = secrets.token_urlsafe(24)
    broker_call("provision", device.code, password)
    info.broker_provisioned = True
    device.status = "provisioned"
    M.audit(db, user, f"devices.provision:{device.id}")
    db.commit()
    return {"device_id": device.id, "mqtt_username": device.code, "mqtt_password": password,
            "telemetry_topic": f"iot/{device.code}/lm393", "command_topic": f"iot/{device.code}/commands",
            "ack_topic": f"iot/{device.code}/ack", "password_shown_once": True}


@router.post("/devices/{device_id}/credentials/rotate")
def rotate_credentials(device_id: int, user=Depends(M.roles("admin")), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    info = details(db, device)
    if not info.broker_provisioned or device.status in {"registered", "decommissioned"}:
        raise HTTPException(409, "Device is not provisioned")
    password = secrets.token_urlsafe(24)
    broker_call("rotate_password", device.code, password)
    M.audit(db, user, f"devices.rotate_credentials:{device.id}")
    db.commit()
    return {"mqtt_username": device.code, "mqtt_password": password, "password_shown_once": True,
            "note": "Update the device configuration with this new password"}


@router.put("/devices/{device_id}/slot")
def assign_slot(device_id: int, body: AssignSlotBody, user=Depends(M.roles("admin")), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    slot = db.get(DeviceSlot, body.slot)
    gpio = 27 if body.slot == "P1" else 26
    if slot:
        slot.device_id, slot.gpio = device.id, gpio
    else:
        db.add(DeviceSlot(device_id=device.id, slot_name=body.slot, gpio=gpio))
    M.audit(db, user, f"devices.assign_slot:{device.id}:{body.slot}")
    db.commit()
    return {"device_id": device.id, "slot": body.slot, "gpio": gpio}


@router.get("/devices/{device_id}/rules")
def get_rules(device_id: int, user=Depends(M.current_user), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    info = details(db, device)
    return {"offline_enabled": info.offline_alert, "full_enabled": info.full_alert,
            "offline_timeout_s": info.offline_timeout_s,
            "effective_offline_timeout_s": max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000)}


@router.put("/devices/{device_id}/rules")
def update_rules(device_id: int, body: RuleBody, user=Depends(M.current_user), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id, permission="configure")
    info = details(db, device)
    info.offline_alert, info.full_alert, info.offline_timeout_s = body.offline_enabled, body.full_enabled, body.offline_timeout_s
    M.audit(db, user, f"devices.rules:{device.id}")
    db.commit()
    return get_rules(device_id, user, db)


@router.get("/devices/{device_id}/configuration")
def get_configuration(device_id: int, user=Depends(M.current_user), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    info = details(db, device)
    pending = db.scalar(select(DeviceCommand).where(DeviceCommand.device_id == device.id,
        DeviceCommand.action == "configure", DeviceCommand.status.in_(["queued", "sent"]))
        .order_by(DeviceCommand.created_at.desc()).limit(1))
    return {"report_interval_ms": info.report_interval_ms,
            "pending": command_view(pending) if pending else None}


def current_gate_control(db, device):
    live = db.get(LiveTelemetry, device.code)
    control = db.get(LiveGateControl, device.code)
    info = details(db, device)
    fresh = bool(live and control and control.boot_id and control.boot_id == live.boot_id
        and control.boot_id == info.last_boot_id and utc(control.received_at) == utc(live.received_at)
        and live.invalidated_at is None and device.status == "active"
        and connectivity(device, info) == "online" and utc(live.received_at) <= M.now() < utc(live.expires_at))
    return control, fresh


@router.get("/devices/{device_id}/gates")
def get_gates(device_id: int, user=Depends(M.current_user), db=Depends(M.session)):
    device = authorize(db, user, device_id=device_id)
    control, fresh = current_gate_control(db, device)
    live = db.get(LiveTelemetry, device.code)
    sensors = db.get(LiveGateSensors, device.code)
    sensors_fresh = bool(fresh and sensors and sensors.boot_id == live.boot_id
                         and utc(sensors.received_at) == utc(live.received_at))
    commands = db.scalars(select(DeviceCommand).where(DeviceCommand.device_id == device.id,
        DeviceCommand.action.in_(["gate", "gate_mode"])).order_by(DeviceCommand.created_at.desc()).limit(100)).all()
    gates = []
    if control:
        for name, state in control.readings.items():
            pending = next((c for c in commands if c.arguments.get("gate") == name
                            and c.status in {"queued", "sent"}), None)
            last = next((c for c in commands if c.arguments.get("gate") == name), None)
            remaining = state["close_remaining_ms"] - int((M.now() - utc(control.received_at)).total_seconds() * 1000)
            gates.append({"id": name, "mode": state["mode"] if fresh else None,
                "target": state["target"] if fresh and state["pwm_ready"] else None,
                "pwm_ready": state["pwm_ready"] if fresh else False,
                "close_remaining_ms": max(0, remaining) if fresh else 0,
                "detected": sensors.readings.get(name, {}).get("detected") if sensors_fresh else None,
                "pending": command_view(pending) if pending else None,
                "last_command": command_view(last) if last else None,
                "position_verified": False})
    return {"device_id": device.id, "supported": control is not None, "fresh": fresh,
        "received_at": utc(control.received_at).isoformat() if control else None,
        "valid_until": utc(live.expires_at).isoformat() if live else None, "gates": gates}


@router.post("/devices/{device_id}/commands", status_code=202)
@serialized
def create_command(device_id: int, body: CommandBody, user=Depends(M.current_user), db=Depends(M.session)):
    is_gate = body.action in {"gate", "gate_mode"}
    if is_gate and user.role != "admin":
        raise HTTPException(403, "Only admins can operate gates")
    permission = "configure" if body.action == "configure" else "control"
    device = authorize(db, user, device_id=device_id, permission=permission)
    arguments = {}
    if is_gate:
        if not body.gate or body.report_interval_ms is not None:
            raise HTTPException(422, "gate commands require a gate and do not accept report_interval_ms")
        arguments["gate"] = body.gate
        if body.action == "gate":
            if body.target is None or body.mode is not None:
                raise HTTPException(422, "gate requires target only")
            arguments["target"] = body.target
        else:
            if body.mode is None or body.target is not None:
                raise HTTPException(422, "gate_mode requires mode only")
            arguments["mode"] = body.mode
    else:
        if any(v is not None for v in (body.gate, body.target, body.mode)):
            raise HTTPException(422, "gate fields are only valid for gate commands")
        if body.action == "configure":
            if body.report_interval_ms is None:
                raise HTTPException(422, "configure requires report_interval_ms")
            arguments["report_interval_ms"] = body.report_interval_ms
        elif body.report_interval_ms is not None:
            raise HTTPException(422, "ping does not accept report_interval_ms")
    if body.idempotency_key:
        previous = db.scalar(select(DeviceCommand).where(DeviceCommand.actor_id == user.id,
            DeviceCommand.idempotency_key == body.idempotency_key))
        if previous:
            original = {k: v for k, v in previous.arguments.items() if k != "revision"}
            if previous.device_id != device.id or previous.action != body.action or original != arguments:
                raise HTTPException(409, "Idempotency key was used for another request")
            return command_view(previous)
    info = details(db, device)
    if device.status not in {"active", "provisioned"} or connectivity(device, info) != "online":
        raise HTTPException(409, "Device is not online and enabled")
    if not receiver_ready():
        raise HTTPException(503, "MQTT receiver is not ready")
    if is_gate:
        control, fresh = current_gate_control(db, device)
        if not fresh or not control or not control.readings[body.gate]["pwm_ready"]:
            raise HTTPException(409, "Gate firmware is not ready")
        if body.action == "gate" and control.readings[body.gate]["mode"] != "manual":
            raise HTTPException(409, "Select manual mode first")
        pending = db.scalars(select(DeviceCommand).where(DeviceCommand.device_id == device.id,
            DeviceCommand.action.in_(["gate", "gate_mode"]), DeviceCommand.status.in_(["queued", "sent"]))).all()
        if any(c.arguments.get("gate") == body.gate for c in pending):
            raise HTTPException(409, "Gate already has a pending command")
        counter = db.get(GateCommandCounter, (device.id, body.gate))
        if counter is None:
            counter = GateCommandCounter(device_id=device.id, gate=body.gate, revision=0)
            db.add(counter)
        counter.revision = max(counter.revision, control.readings[body.gate]["revision"]) + 1
        if counter.revision > 0xFFFFFFFF:
            raise HTTPException(409, "Gate revision exhausted")
        arguments["revision"] = counter.revision
    latest = db.get(LiveTelemetry, device.code)
    if latest is None:
        latest = db.scalar(select(M.Telemetry).where(M.Telemetry.device_code == device.code)
                           .order_by(M.Telemetry.id.desc()).limit(1))
    command = DeviceCommand(id=uuid.uuid4().hex, device_id=device.id, actor_id=user.id,
        action=body.action, arguments=arguments, idempotency_key=body.idempotency_key,
        expires_at=M.now() + timedelta(seconds=body.timeout_s), target_boot_id=info.last_boot_id,
        uptime_deadline_s=(latest.uptime_s + int(max(0, (M.now() - utc(latest.received_at)).total_seconds()))
                           + body.timeout_s) if latest else None)
    db.add(command)
    M.audit(db, user, f"commands.create:{device.id}:{command.id}:{body.action}")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Duplicate command request")
    return command_view(command)


@router.get("/devices/{device_id}/commands")
def list_commands(device_id: int, limit: int = 50, user=Depends(M.current_user), db=Depends(M.session)):
    authorize(db, user, device_id=device_id)
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    return [command_view(item) for item in db.scalars(select(DeviceCommand)
        .where(DeviceCommand.device_id == device_id).order_by(DeviceCommand.created_at.desc()).limit(limit))]


@router.get("/commands/{command_id}")
def get_command(command_id: str, user=Depends(M.current_user), db=Depends(M.session)):
    item = db.get(DeviceCommand, command_id)
    if not item:
        raise HTTPException(404, "Command not found")
    authorize(db, user, device_id=item.device_id)
    return command_view(item)


def alert_view(alert, info):
    return {"id": alert.id, "message": alert.message,
            "created_at": utc(alert.created_at).isoformat(), "device_id": info.device_id if info else None,
            "kind": info.kind if info else "legacy", "active": bool(info and info.active_key),
            "resolved_at": utc(info.resolved_at).isoformat() if info and info.resolved_at else None,
            "acknowledged": bool(info and info.acknowledged_at),
            "acknowledged_by": info.acknowledged_by if info else None,
            "acknowledged_at": utc(info.acknowledged_at).isoformat() if info and info.acknowledged_at else None}


def scoped_alerts(db, user, limit, active_only):
    query = select(M.Alert, AlertDetails).join(AlertDetails, AlertDetails.alert_id == M.Alert.id).where(
        AlertDetails.kind.in_(ALERT_KINDS))
    codes = visible_codes(db, user)
    if codes is not None:
        device_ids = select(M.Device.id).where(M.Device.code.in_(codes))
        query = query.where(AlertDetails.device_id.in_(device_ids))
    if active_only:
        query = query.where(AlertDetails.active_key.is_not(None))
    return [alert_view(alert, info) for alert, info in db.execute(query.order_by(M.Alert.id.desc()).limit(limit))]


@router.post("/alerts/{alert_id}/acknowledge")
@serialized
def acknowledge_alert(alert_id: int, user=Depends(M.current_user), db=Depends(M.session)):
    """Record who reviewed an alert. This never resolves it; resolution stays automatic."""
    if user.role not in {"admin", "operator"}:
        raise HTTPException(403, "Insufficient permissions")
    row = db.execute(select(M.Alert, AlertDetails).join(AlertDetails, AlertDetails.alert_id == M.Alert.id)
                     .where(M.Alert.id == alert_id, AlertDetails.kind.in_(ALERT_KINDS))).first()
    if not row:
        raise HTTPException(404, "Alert not found")
    alert, info = row
    # Out-of-scope alerts look identical to missing ones.
    try:
        authorize(db, user, device_id=info.device_id)
    except HTTPException as error:
        if error.status_code == 404:
            raise HTTPException(404, "Alert not found")
        raise
    if info.acknowledged_at is None:
        info.acknowledged_by, info.acknowledged_at = user.id, M.now()
        M.audit(db, user, f"alerts.acknowledge:{alert.id}:device:{info.device_id}")
        db.commit()
    return alert_view(alert, info)


@router.get("/parking/events")
def parking_events(device_id: int | None = None, from_at: datetime | None = None,
                   to_at: datetime | None = None, before_id: int | None = None, limit: int = 50,
                   user=Depends(M.current_user), db=Depends(M.session)):
    if not 1 <= limit <= 200:
        raise HTTPException(422, "limit must be 1..200")
    query = select(ParkingEvent)
    if device_id is not None:
        authorize(db, user, device_id=device_id)
        query = query.where(ParkingEvent.device_id == device_id)
    else:
        codes = visible_codes(db, user)
        if codes is not None:
            query = query.where(ParkingEvent.device_id.in_(select(M.Device.id).where(M.Device.code.in_(codes))))
    query = time_filter(query, ParkingEvent.occurred_at, from_at, to_at)
    if before_id is not None:
        query = query.where(ParkingEvent.id < before_id)
    return [{"id": item.id, "device_id": item.device_id, "slot": item.slot_name, "kind": item.kind,
             "occupied": item.occupied, "occurred_at": utc(item.occurred_at).isoformat()}
            for item in db.scalars(query.order_by(ParkingEvent.id.desc()).limit(limit))]


@router.get("/telemetry/statistics")
def statistics(device_id: str = "esp32_01", from_at: datetime | None = None,
               to_at: datetime | None = None, user=Depends(M.current_user), db=Depends(M.session)):
    if device_id != "simulator" or user.role != "admin":
        authorize(db, user, code=device_id)
    from_at = from_at or M.now() - timedelta(hours=24)
    to_at = to_at or M.now()
    bucket = func.strftime("%Y-%m-%dT%H:00:00Z", M.Telemetry.received_at)
    query = select(bucket.label("hour"), M.TelemetrySlot.slot_name,
        func.count().label("samples"), func.sum(case((M.TelemetrySlot.occupied.is_(True), 1), else_=0)).label("occupied_samples"))
    query = query.join(M.Telemetry, M.Telemetry.id == M.TelemetrySlot.telemetry_id).where(M.Telemetry.device_code == device_id)
    query = time_filter(query, M.Telemetry.received_at, from_at, to_at)
    rows = db.execute(query.group_by(bucket, M.TelemetrySlot.slot_name).order_by(bucket, M.TelemetrySlot.slot_name))
    return {"basis": "sample_count_not_parking_duration", "device_id": device_id,
        "capture_policy": "change_or_60s_checkpoint",
        "buckets": [{"hour": hour, "slot": name, "samples": total, "occupied_samples": occupied,
            "occupied_sample_percent": round(100 * occupied / total, 2)} for hour, name, total, occupied in rows]}


@router.get("/parking/utilization")
def utilization(device_id: str = "esp32_01", from_at: datetime | None = None,
                to_at: datetime | None = None, user=Depends(M.current_user), db=Depends(M.session)):
    authorize(db, user, code=device_id)
    end, start = utc(to_at or M.now()), utc(from_at or M.now() - timedelta(hours=24))
    # Reuse strict timezone and range validation; hourly aggregates have hour granularity.
    time_filter(select(HourlyOccupancy), HourlyOccupancy.hour, from_at, to_at)
    if start >= end or end - start > timedelta(days=366):
        raise HTTPException(422, "duration range must be ordered and at most 366 days")
    start = start.replace(minute=0, second=0, microsecond=0)
    end_hour = end.replace(minute=0, second=0, microsecond=0)
    stop = end_hour if end == end_hour else end_hour + timedelta(hours=1)
    rows = db.scalars(select(HourlyOccupancy).where(HourlyOccupancy.device_code == device_id,
        HourlyOccupancy.hour >= start, HourlyOccupancy.hour < stop).order_by(HourlyOccupancy.hour, HourlyOccupancy.slot_name))
    from app.storage import policy
    return {"basis": "observed_duration", "range_mode": "whole_hours", "from_at": start.isoformat(),
        "to_at": stop.isoformat(), "generated_at": M.now().isoformat(), "storage_policy": policy(),
        "buckets": [{"hour": utc(r.hour).isoformat(), "slot": r.slot_name,
            "occupied_seconds": round(r.occupied_s, 3), "available_seconds": round(r.available_s, 3),
            "unknown_seconds": round(r.unknown_s, 3),
            "observed_seconds": round(r.occupied_s + r.available_s, 3),
            "occupied_observed_percent": round(100 * r.occupied_s / (r.occupied_s + r.available_s), 2)
                if r.occupied_s + r.available_s else None} for r in rows]}


@router.get("/storage/policy")
def storage_policy(user=Depends(M.roles("admin"))):
    from app.storage import policy
    return policy()


@router.get("/telemetry/export.csv")
def export_csv(device_id: str = "esp32_01", from_at: datetime | None = None,
               to_at: datetime | None = None, limit: int = 10000,
               user=Depends(M.current_user), db=Depends(M.session)):
    if device_id != "simulator" or user.role != "admin":
        authorize(db, user, code=device_id)
    if not 1 <= limit <= 10000:
        raise HTTPException(422, "limit must be 1..10000; narrow the time range for larger exports")
    query = select(M.Telemetry, M.TelemetrySlot).join(M.TelemetrySlot,
        M.TelemetrySlot.telemetry_id == M.Telemetry.id).where(M.Telemetry.device_code == device_id)
    query = time_filter(query, M.Telemetry.received_at, from_at, to_at)
    rows = list(db.execute(query.order_by(M.Telemetry.id.desc(), M.TelemetrySlot.slot_name).limit(limit)))
    M.audit(db, user, f"telemetry.export_csv:{device_id}")
    db.commit()
    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["received_at_utc", "device_id", "uptime_s", "slot", "do", "occupied"])
        yield buffer.getvalue()
        for reading, sample in rows:
            buffer.seek(0)
            buffer.truncate(0)
            code = "'" + reading.device_code if reading.device_code.startswith(("=", "+", "-", "@")) else reading.device_code
            writer.writerow([utc(reading.received_at).isoformat(), code, reading.uptime_s,
                             sample.slot_name, sample.do_level, int(sample.occupied)])
            yield buffer.getvalue()
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="parking-telemetry.csv"'})
