"""Bounded live state, sparse history, duration rollups and batched retention."""
from datetime import timedelta
from sqlalchemy import delete, select
from app import main as M
from app.domain import (DeviceDetails, DeviceSlot, HourlyOccupancy, LiveTelemetry, ParkingEvent,
                        SeenPacket, StorageState, LiveGateSensors, LiveGateControl)
from app.domain_service import utc

CHECKPOINT_SECONDS = 60
SNAPSHOT_DAYS = 3
EVENT_DAYS = 90
ROLLUP_DAYS = 365
PACKET_DAYS = 1
BATCH_SIZE = 10000


def policy():
    return {"history_mode": "change_or_checkpoint", "checkpoint_seconds": CHECKPOINT_SECONDS,
            "snapshot_retention_days": SNAPSHOT_DAYS, "event_retention_days": EVENT_DAYS,
            "rollup_retention_days": ROLLUP_DAYS, "legacy_packet_retention_days": PACKET_DAYS,
            "database": "sqlite" if M.DATABASE_URL.startswith("sqlite") else "configured"}


def bootstrap_live(db, device):
    """Adopt the last legacy sample without altering historical rows."""
    live = db.get(LiveTelemetry, device.code)
    if live:
        return live
    row = db.scalar(select(M.Telemetry).where(M.Telemetry.device_code == device.code)
                    .order_by(M.Telemetry.id.desc()).limit(1))
    if not row:
        return None
    info = db.get(DeviceDetails, device.id)
    stamp = utc(row.received_at)
    timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 10
    levels = [{"name": s.slot_name, "do": s.do_level, "occupied": s.occupied}
              for s in db.scalars(select(M.TelemetrySlot).where(M.TelemetrySlot.telemetry_id == row.id)
                                  .order_by(M.TelemetrySlot.slot_name))]
    live = LiveTelemetry(device_code=device.code, received_at=stamp,
        expires_at=stamp + timedelta(seconds=timeout), accounted_until=stamp,
        invalidated_at=stamp if info and info.forced_offline else None,
        history_at=stamp, history_id=row.id, uptime_s=row.uptime_s, levels=levels,
        operational=device.status == "active", boot_id=info.last_boot_id if info else None,
        seq=info.last_seq if info else None)
    db.add(live)
    db.flush()
    return live


def advance(db, live, end):
    """Account each interval once; expired/offline time remains explicitly unknown."""
    end = utc(end)
    start = max(utc(live.accounted_until), end - timedelta(days=ROLLUP_DAYS))
    if start >= end:
        return
    valid_end = utc(live.expires_at) if live.operational else utc(live.received_at)
    if live.invalidated_at:
        valid_end = min(valid_end, utc(live.invalidated_at))
    samples = {s["name"]: s for s in live.levels}
    device = db.scalar(select(M.Device).where(M.Device.code == live.device_code))
    if device:
        for name in db.scalars(select(DeviceSlot.slot_name).where(DeviceSlot.device_id == device.id)):
            samples.setdefault(name, {"name": name, "occupied": None})
    while start < end:
        hour = start.replace(minute=0, second=0, microsecond=0)
        stop = min(end, hour + timedelta(hours=1))
        known = max(0.0, (min(stop, valid_end) - start).total_seconds())
        elapsed = (stop - start).total_seconds()
        for sample in samples.values():
            key = (live.device_code, sample["name"], hour)
            bucket = db.get(HourlyOccupancy, key)
            if not bucket:
                bucket = HourlyOccupancy(device_code=live.device_code, slot_name=sample["name"],
                    hour=hour, occupied_s=0, available_s=0, unknown_s=0)
                db.add(bucket)
            measured = known if isinstance(sample["occupied"], bool) else 0
            if sample["occupied"] is True:
                bucket.occupied_s += measured
            elif sample["occupied"] is False:
                bucket.available_s += measured
            bucket.unknown_s += elapsed - measured
        start = stop
    live.accounted_until = end


def invalidate(db, device, at):
    live = bootstrap_live(db, device)
    if live:
        advance(db, live, at)
        live.invalidated_at = min(utc(live.invalidated_at), at) if live.invalidated_at else at


def save_packet(db, device, item, stamp, info, gap):
    live = bootstrap_live(db, device) if device else db.get(LiveTelemetry, item.device_id)
    levels = [{"name": "P1", "do": item.do, "occupied": item.detected}]
    if item.do2 is not None:
        levels.append({"name": "P2", "do": item.do2, "occupied": item.detected2})
    if live and stamp < utc(live.received_at):
        return False
    checkpoint = (not live or live.history_at is None or
                  (stamp - utc(live.history_at)).total_seconds() >= CHECKPOINT_SECONDS)
    changed = not live or live.levels != levels or live.boot_id != item.boot_id or gap
    if live:
        advance(db, live, stamp)
    else:
        live = LiveTelemetry(device_code=item.device_id, received_at=stamp,
            expires_at=stamp, accounted_until=stamp, uptime_s=item.uptime_s,
            levels=levels, operational=True)
        db.add(live)
    if checkpoint or changed:
        row = M.Telemetry(device_code=item.device_id, uptime_s=item.uptime_s,
            do_level=item.do, detected=item.detected, received_at=stamp)
        db.add(row)
        db.flush()
        for s in levels:
            db.add(M.TelemetrySlot(telemetry_id=row.id, slot_name=s["name"],
                                  do_level=s["do"], occupied=s["occupied"]))
        live.history_at, live.history_id = stamp, row.id
    timeout = max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000) if info else 10
    live.received_at, live.expires_at = stamp, stamp + timedelta(seconds=timeout)
    live.accounted_until, live.invalidated_at = stamp, None
    live.uptime_s, live.levels = item.uptime_s, levels
    live.operational = device.status == "active" if device else False
    live.boot_id, live.seq = item.boot_id, item.seq
    gates = db.get(LiveGateSensors, item.device_id)
    if item.gate_sensors is not None:
        if gates is None:
            gates = LiveGateSensors(device_code=item.device_id)
            db.add(gates)
        gates.received_at, gates.boot_id = stamp, item.boot_id
        gates.readings = item.gate_sensors.model_dump()
    elif gates is not None:
        # Old firmware or an unavailable sensor snapshot must not refresh old gate data.
        db.delete(gates)
    control = db.get(LiveGateControl, item.device_id)
    if item.gate_control is not None:
        if control is None:
            control = LiveGateControl(device_code=item.device_id)
            db.add(control)
        control.received_at, control.boot_id = stamp, item.boot_id
        control.readings = item.gate_control.model_dump()
    elif control is not None:
        db.delete(control)
    return True


def live_view(live, fresh):
    return {"id": live.history_id, "device_id": live.device_code,
            "uptime_s": live.uptime_s, "do": live.levels[0]["do"],
            "detected": live.levels[0]["occupied"], "received_at": utc(live.received_at).isoformat(),
            "slots": [{**s, "gpio": 27 if s["name"] == "P1" else 26} for s in live.levels],
            "simulated": live.device_code == "simulator", "fresh": bool(fresh),
            "source": "live_state", "history_mode": "change_or_checkpoint"}


def gate_sensor_view(db, live, fresh):
    gates = db.get(LiveGateSensors, live.device_code)
    if gates is None:
        return None
    valid = bool(fresh and gates.boot_id == live.boot_id
                 and utc(gates.received_at) == utc(live.received_at))
    return {"received_at": utc(gates.received_at).isoformat(), "fresh": valid,
            "sensors": {name: {"gpio": item["gpio"],
                "do": item["do"] if valid else None,
                "detected": item["detected"] if valid else None}
                for name, item in gates.readings.items()}}


def due(db, key, seconds, at):
    state = db.get(StorageState, key)
    if state and (at - utc(state.at)).total_seconds() < seconds:
        return False
    if state:
        state.at = at
    else:
        db.add(StorageState(key=key, at=at))
    return True


def maintain(db, at, force=False):
    if force or due(db, "duration_rollup", 30, at):
        for device in db.scalars(select(M.Device)):
            live = bootstrap_live(db, device)
            if live:
                advance(db, live, at)
    if not force and not due(db, "retention", 300, at):
        return
    # Delete children first. Latest state is separate and survives history expiry.
    ids = list(db.scalars(select(M.Telemetry.id).where(
        M.Telemetry.received_at < at - timedelta(days=SNAPSHOT_DAYS)).limit(BATCH_SIZE)))
    if ids:
        db.execute(delete(M.TelemetrySlot).where(M.TelemetrySlot.telemetry_id.in_(ids)))
        for live in db.scalars(select(LiveTelemetry).where(LiveTelemetry.history_id.in_(ids))):
            live.history_id = None
        db.execute(delete(M.Telemetry).where(M.Telemetry.id.in_(ids)))
    for model, column, days in [(ParkingEvent, ParkingEvent.occurred_at, EVENT_DAYS),
                                 (SeenPacket, SeenPacket.received_at, PACKET_DAYS),
                                 (HourlyOccupancy, HourlyOccupancy.hour, ROLLUP_DAYS)]:
        # A subquery over primary keys keeps each maintenance transaction bounded.
        keys = list(model.__table__.primary_key.columns)
        rows = list(db.execute(select(*keys).where(column < at - timedelta(days=days)).limit(BATCH_SIZE)))
        if rows:
            from sqlalchemy import tuple_
            db.execute(delete(model).where(tuple_(*keys).in_([tuple(row) for row in rows])))
