import os, sys, tempfile
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import create_app, db, config
import seed as seedmod

def make_client(simulated_work_ms=0):
    config.SIMULATED_WORK_MS = simulated_work_ms
    path = os.path.join(tempfile.mkdtemp(), "t.db")
    c = db.connect(path); seedmod.seed(c, "unit-test-password"); c.close()
    app = create_app({"DB_PATH": path, "TESTING": True})
    return app.test_client(), path

def login(client, username):
    r = client.post("/api/login", json={"username": username, "password": "unit-test-password"})
    return {"Authorization": "Bearer " + r.get_json()["token"]}
