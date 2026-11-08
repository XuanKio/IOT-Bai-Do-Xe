import logging
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app import main as M
from app.coordination import serialized
from app.domain import (AlertDetails, DeviceBoot, DeviceCommand, DeviceDetails, DeviceGrant,
                        DeviceSlot, LiveTelemetry, ParkingEvent, SeenPacket)

log = logging.getLogger(__name__)
TERMINAL = {"acknowledged", "failed", "timed_out", "cancelled"}
ALERT_KINDS = ("parking_full", "device_offline")
# (receiver object, time it was first seen ready); lets a restarted backend wait for devices to report.
_receiver_ready = [None, None]


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def offline_condition(device, info, state, at):
    """Decide the device_offline alert: True raise/keep, False resolve, None leave unchanged.

    Only a device that was seen before, should be active and then went silent can alert.
    Never-seen and maintenance/revoked/decommissioned devices never do. While the MQTT
    receiver is down or still inside its restart grace period silence proves nothing, so
    existing alerts are held (not resolved, not duplicated) and new ones are not raised.
    """
    if not info or not info.offline_alert or device.status != "active" or not info.last_seen or state != "offline":
        return False
    receiver = getattr(M.app.state, "mqtt_receiver", None)
    if not receiver_ready() or _receiver_ready[0] is not receiver or _receiver_ready[1] is None:
        return None
    timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000)
    return True if (at - _receiver_ready[1]).total_seconds() >= timeout else None


def details(db, device):
    value = db.get(DeviceDetails, device.id)
    if not value:
        value = DeviceDetails(device_id=device.id)
        db.add(value)
        db.flush()
    return value


def visible_codes(db, user):
    if user.role == "admin":
        return None
    return list(db.scalars(select(M.Device.code).join(DeviceGrant, DeviceGrant.device_id == M.Device.id)
                           .where(DeviceGrant.user_id == user.id)))


def authorize(db, user, device_id=None, code=None, permission="read"):
    device = db.get(M.Device, device_id) if device_id is not None else db.scalar(
        select(M.Device).where(M.Device.code == code))
    if not device:
        raise HTTPException(404, "Device not found")
    if user.role != "admin":
        grant = db.get(DeviceGrant, (device.id, user.id))
        if not grant:
            raise HTTPException(404, "Device not found")
        if permission != "read" and (user.role != "operator" or not getattr(grant, "can_" + permission)):
            raise HTTPException(403, "Insufficient device permission")
    return device


def receiver_ready():
    receiver = getattr(M.app.state, "mqtt_receiver", None)
    return bool(receiver and receiver.connected and receiver.subscribed)


def connectivity(device, info, at=None):
    if device.status in {"revoked", "decommissioned", "registered"}:
        return "disabled" if device.status != "registered" else "unknown"
    if not info or not info.last_seen:
        return "unknown"
    age = ((at or M.now()) - utc(info.last_seen)).total_seconds()
    timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000)
    return "online" if receiver_ready() and not info.forced_offline and 0 <= age < timeout else "offline"


def seed_physical(db):
    device = db.scalar(select(M.Device).where(M.Device.code == "esp32_01"))
    if not device:
        device = M.Device(code="esp32_01", name="ESP32 bai xe P1/P2", status="active")
        db.add(device)
        db.flush()
        info = details(db, device)
        info.broker_provisioned = True
        info.location = "Bai xe mo hinh"
        info.hardware = "ESP32-D0WD-V3"
    else:
        details(db, device)
    for name, gpio in (("P1", 27), ("P2", 26)):
        if not db.get(DeviceSlot, name):
            db.add(DeviceSlot(slot_name=name, device_id=device.id, gpio=gpio))


@serialized
def persist_reading(item, received_at):
    from app.storage import save_packet
    received_at = utc(received_at)
    with M.Sessions() as db:
        device = db.scalar(select(M.Device).where(M.Device.code == item.device_id))
        simulated = item.device_id == "simulator"
        info, previous_seen = None, None
        if not simulated:
            if not device or device.status not in {"active", "provisioned", "maintenance"}:
                log.warning("Ignored telemetry from an unregistered or disabled device")
                return False
            info = details(db, device)
            if not info.broker_provisioned:
                return False
            previous_seen = utc(info.last_seen)
        if item.boot_id is not None:
            if info:
                # The per-device watermark replaces an unbounded row per packet.
                if info.last_boot_id == item.boot_id and info.last_seq is not None and item.seq <= info.last_seq:
                    return False
                if info.last_boot_id != item.boot_id:
                    if db.get(DeviceBoot, (device.id, item.boot_id)):
                        return False
                    db.add(DeviceBoot(device_id=device.id, boot_id=item.boot_id))
                info.last_boot_id, info.last_seq = item.boot_id, item.seq
            else:
                packet_key = (item.device_id, item.boot_id, item.seq)
                if db.get(SeenPacket, packet_key):
                    return False
                db.add(SeenPacket(device_code=item.device_id, boot_id=item.boot_id,
                                  seq=item.seq, received_at=received_at))
        timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 10
        live = db.get(LiveTelemetry, item.device_id)
        gap = previous_seen is None or (received_at - previous_seen).total_seconds() >= timeout or bool(info and info.forced_offline) or bool(live and live.invalidated_at)
        if info and item.report_interval_ms is not None:
            info.report_interval_ms = item.report_interval_ms
        if not save_packet(db, device, item, received_at, info, gap):
            return False
        levels = [("P1", item.do, item.detected)]
        if item.do2 is not None:
            levels.append(("P2", item.do2, item.detected2))
        for name, level, occupied in levels:
            assignment = db.get(DeviceSlot, name)
            if not simulated and assignment and assignment.device_id == device.id and device.status == "active":
                slot = db.scalar(select(M.Slot).where(M.Slot.name == name))
                if slot and (gap or slot.occupied != occupied):
                    db.add(ParkingEvent(device_id=device.id, slot_name=name,
                        kind="initial" if previous_seen is None else ("after_gap" if gap else ("occupied" if occupied else "available")),
                        occupied=occupied, occurred_at=received_at))
                if slot:
                    slot.occupied = occupied
        if info:
            info.last_seen, info.forced_offline = received_at, False
            if item.firmware:
                device.firmware = item.firmware
            if item.hardware:
                info.hardware = item.hardware
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
        return True


def slot_views(db, user=None):
    allowed = visible_codes(db, user) if user else None
    values = []
    for slot in db.scalars(select(M.Slot).order_by(M.Slot.id)):
        assignment = db.get(DeviceSlot, slot.name)
        device = db.get(M.Device, assignment.device_id) if assignment else None
        if user and user.role != "admin" and (not device or device.code not in allowed):
            continue
        sample = None
        fresh = False
        stamp = None
        if device:
            info = db.get(DeviceDetails, device.id)
            live = db.get(LiveTelemetry, device.code)
            if not live:
                sample = db.execute(select(M.TelemetrySlot, M.Telemetry).join(M.Telemetry,
                    M.TelemetrySlot.telemetry_id == M.Telemetry.id).where(
                        M.TelemetrySlot.slot_name == slot.name, M.Telemetry.device_code == device.code)
                    .order_by(M.Telemetry.id.desc()).limit(1)).first()
            current = next((s for s in live.levels if s["name"] == slot.name), None) if live else None
            if live:
                stamp = utc(live.received_at)
                fresh = (current is not None and live.operational and live.invalidated_at is None
                         and device.status == "active" and connectivity(device, info) == "online"
                         and stamp <= M.now() < utc(live.expires_at))
            elif sample:
                stamp = utc(sample[1].received_at)
                timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 5
                fresh = (device.status == "active" and connectivity(device, info) == "online"
                         and 0 <= (M.now() - stamp).total_seconds() < timeout)
        occupied = current["occupied"] if device and live and current else (sample[0].occupied if sample else None)
        values.append({"id": slot.id, "name": slot.name, "device_id": device.id if device else None,
            "occupied": occupied if fresh else None,
            "gpio": assignment.gpio if assignment else None, "fresh": bool(fresh),
            "updated_at": stamp.isoformat() if stamp else None})
    return values


def set_alert(db, device, kind, active, message):
    key = f"{device.id}:{kind}"
    meta = db.scalar(select(AlertDetails).where(AlertDetails.active_key == key))
    if active and not meta:
        alert = M.Alert(message=message)
        db.add(alert)
        db.flush()
        db.add(AlertDetails(alert_id=alert.id, device_id=device.id, kind=kind, active_key=key))
    elif not active and meta:
        meta.active_key, meta.resolved_at = None, M.now()


@serialized
def acknowledge_command(item, received_at):
    with M.Sessions() as db:
        device = db.scalar(select(M.Device).where(M.Device.code == item.device_id))
        command = db.get(DeviceCommand, item.command_id)
        if (not device or not command or command.device_id != device.id or command.status in TERMINAL
                or device.status not in {"active", "provisioned"}):
            return
        if command.action in {"gate", "gate_mode"}:
            info = details(db, device)
            if item.boot_id != command.target_boot_id or item.boot_id != info.last_boot_id:
                return
        if utc(command.expires_at) <= received_at:
            command.status, command.completed_at = "timed_out", received_at
            db.commit()
            return
        success = item.status == "succeeded"
        if success and command.action in {"gate", "gate_mode"}:
            result = item.result
            success = (result.get("gate") == command.arguments["gate"]
                and type(result.get("revision")) is int
                and result["revision"] == command.arguments["revision"]
                and result.get("pwm_ready") is True)
            if command.action == "gate":
                success = success and result.get("target") == command.arguments["target"] and result.get("mode") == "manual"
            else:
                success = success and result.get("mode") == command.arguments["mode"]
        if success and command.action == "configure":
            success = item.result.get("report_interval_ms") == command.arguments.get("report_interval_ms")
            if success:
                info = details(db, device)
                info.report_interval_ms = command.arguments["report_interval_ms"]
        command.status = "acknowledged" if success else "failed"
        command.completed_at, command.result = received_at, item.result
        command.error = item.error if not success else None
        if not success and not command.error:
            command.error = "Device did not confirm the requested configuration"
        db.commit()


@serialized
def receive_status(item, received_at):
    with M.Sessions() as db:
        device = db.scalar(select(M.Device).where(M.Device.code == item.device_id))
        if not device or device.status not in {"active", "provisioned", "maintenance"}:
            return
        info = details(db, device)
        # A queued will from a previous boot must not take the new boot offline.
        if item.boot_id and info.last_boot_id and item.boot_id != info.last_boot_id:
            return
        if item.state == "offline":
            from app.storage import invalidate
            invalidate(db, device, received_at)
            info.forced_offline = True
        else:
            info.last_seen, info.forced_offline = received_at, False
        db.commit()


@serialized
def runtime_tick():
    to_publish = []
    receiver = getattr(M.app.state, "mqtt_receiver", None)
    if not receiver_ready():
        _receiver_ready[0], _receiver_ready[1] = None, None
    elif _receiver_ready[0] is not receiver or _receiver_ready[1] is None:
        _receiver_ready[0], _receiver_ready[1] = receiver, M.now()
    with M.Sessions() as db:
        # Retire alerts from unsupported kinds without deleting their history.
        for alert in db.scalars(select(AlertDetails).where(
                AlertDetails.kind.not_in(ALERT_KINDS), AlertDetails.active_key.is_not(None))):
            alert.active_key, alert.resolved_at = None, M.now()
        for device in db.scalars(select(M.Device)):
            info = details(db, device)
            state = connectivity(device, info)
            if state != info.connection_state:
                if state != "online":
                    from app.storage import invalidate
                    invalidate(db, device, M.now())
                if info.connection_state == "online" and state != "online":
                    for assignment in db.scalars(select(DeviceSlot).where(DeviceSlot.device_id == device.id)):
                        db.add(ParkingEvent(device_id=device.id, slot_name=assignment.slot_name,
                                            kind="unknown", occupied=None))
                info.connection_state = state
            device_slots = [slot for slot in slot_views(db) if slot["device_id"] == device.id]
            full = bool(device_slots) and all(slot["occupied"] is True for slot in device_slots)
            set_alert(db, device, "parking_full", full and info.full_alert,
                      f"Khu vuc cua {device.code} da het cho do")
            offline = offline_condition(device, info, state, M.now())
            if offline is not None:
                set_alert(db, device, "device_offline", offline, f"Thiet bi {device.code} mat ket noi")
        for command in db.scalars(select(DeviceCommand).where(DeviceCommand.status.in_(["queued", "sent"]))):
            device = db.get(M.Device, command.device_id)
            gate_cancelled = False
            if device and command.action in {"gate", "gate_mode"}:
                info = details(db, device)
                actor = db.get(M.User, command.actor_id)
                gate_cancelled = (not actor or not actor.active or actor.role != "admin"
                    or command.target_boot_id != info.last_boot_id or connectivity(device, info) != "online")
            if not device or device.status not in {"active", "provisioned"}:
                command.status, command.completed_at = "cancelled", M.now()
                command.error = "Device is not enabled"
            elif gate_cancelled:
                command.status, command.completed_at = "cancelled", M.now()
                command.error = "Gate control session is no longer valid"
            elif utc(command.expires_at) <= M.now():
                command.status, command.completed_at = "timed_out", M.now()
                command.error = "No device acknowledgement before deadline"
            elif receiver_ready() and command.attempts < 3 and (
                    command.last_sent_at is None or (M.now() - utc(command.last_sent_at)).total_seconds() >= 2):
                command.status, command.last_sent_at = "sent", M.now()
                command.attempts += 1
                to_publish.append((device.code, {"command_id": command.id, "action": command.action,
                    "arguments": command.arguments, "expires_unix": int(utc(command.expires_at).timestamp()),
                    "boot_id": command.target_boot_id, "uptime_deadline_s": command.uptime_deadline_s}))
        from app.storage import maintain
        maintain(db, M.now())
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return
    receiver = getattr(M.app.state, "mqtt_receiver", None)
    for code, payload in to_publish:
        if receiver:
            receiver.publish_command(code, payload)
