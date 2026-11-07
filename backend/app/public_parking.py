"""Minimal, scoped parking information for drivers; no device internals."""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends
from app import main as M
from app.domain import DeviceDetails, LiveTelemetry
from app.domain_service import slot_views, utc

router = APIRouter()


@router.get("/parking/overview")
def parking_overview(user=Depends(M.current_user), db=Depends(M.session)):
    items = slot_views(db, user)
    now = M.now()
    values = []
    for slot in items:
        state = "unknown" if slot["occupied"] is None else "occupied" if slot["occupied"] else "available"
        info = db.get(DeviceDetails, slot["device_id"]) if slot["device_id"] else None
        until = None
        if slot["updated_at"] and info:
            stamp = datetime.fromisoformat(slot["updated_at"])
            until = stamp + timedelta(seconds=max(info.offline_timeout_s, info.report_interval_ms * 3 / 1000))
            device = db.get(M.Device, slot["device_id"])
            live = db.get(LiveTelemetry, device.code) if device else None
            if live:
                until = min(until, utc(live.expires_at))
        values.append({"name": slot["name"], "status": state, "updated_at": slot["updated_at"],
                       "valid_until": until.isoformat() if until and state != "unknown" else None,
                       "zone": "A"})
    count = {key: sum(s["status"] == key for s in values) for key in ("available", "occupied", "unknown")}
    return {"name": "Nhà xe mô hình", "map_note": "Sơ đồ mô phỏng · Vị trí minh họa",
            "capacity": len(values), **count, "slots": values, "generated_at": now.isoformat(),
            "refresh_seconds": 3}
