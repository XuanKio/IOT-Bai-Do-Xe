"""Create a local admin only if it does not already exist."""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
credentials = json.loads((ROOT / "mqtt/runtime/credentials.json").read_text(encoding="utf-8"))
os.environ["DATABASE_URL"] = "sqlite:///" + (ROOT / "backend/parking.db").as_posix()
os.environ["JWT_SECRET"] = credentials["jwt_secret"]

from sqlalchemy import select
from app.main import Base, Sessions, User, engine, hasher

Base.metadata.create_all(engine)
with Sessions() as db:
    if not db.scalar(select(User).where(User.username == "mqtt_admin")):
        db.add(User(username="mqtt_admin", password_hash=hasher.hash(credentials["admin_password"]), role="admin"))
        db.commit()
        print("Created mqtt_admin; password is in mqtt/runtime/THONG_TIN_DANG_NHAP.txt")
    else:
        print("Existing mqtt_admin preserved.")
