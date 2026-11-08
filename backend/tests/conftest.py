import os
import tempfile
from pathlib import Path
import pytest

os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(tempfile.mkdtemp()) / "test.db")
os.environ["JWT_SECRET"] = "test-secret-only-never-use-in-production"
os.environ["MQTT_ENABLED"] = "0"
os.environ["BACKGROUND_ENABLED"] = "0"
os.environ.pop("MQTT_ADMIN_PASSWORD", None)

from app import main as M
from app.domain_service import seed_physical


class FakeBroker:
    def __init__(self):
        self.clients = {}
    def provision(self, code, password):
        self.clients[code] = {"enabled": True, "password": password}
    def set_enabled(self, code, enabled):
        self.clients.setdefault(code, {})["enabled"] = enabled
    def rotate_password(self, code, password):
        self.clients.setdefault(code, {})["password"] = password


@pytest.fixture(autouse=True)
def isolated_database():
    M.Base.metadata.drop_all(M.engine)
    M.Base.metadata.create_all(M.engine)
    with M.Sessions() as db:
        db.add_all([M.Slot(name="P1", occupied=None), M.Slot(name="P2", occupied=None)])
        db.flush()
        seed_physical(db)
        db.commit()
    yield


@pytest.fixture
def fake_broker():
    return FakeBroker()
