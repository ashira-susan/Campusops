import unittest, sys, os
from helpers import make_client, login
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from app import triage

class TriageRules(unittest.TestCase):
    def test_deterministic(self):
        a = triage.suggest("Projector not working in room 201"); b = triage.suggest("Projector not working in room 201")
        self.assertEqual(a, b)
    def test_safety_is_p1(self):
        s = triage.suggest("Smoke coming from the socket"); self.assertEqual((s["category"], s["priority"]), ("safety", "P1"))
    def test_failure_core_category_is_p2(self):
        s = triage.suggest("Air conditioner not working"); self.assertEqual((s["category"], s["priority"]), ("hvac", "P2"))
    def test_minor_is_p4_with_explanation(self):
        s = triage.suggest("Scuffed paint near entrance"); self.assertEqual(s["priority"], "P4"); self.assertIn("R5", s["explanation"])

class TicketTests(unittest.TestCase):
    def setUp(self):
        self.c, _ = make_client()
        self.fm, self.t1, self.t2, self.st = (login(self.c, u) for u in ("fm", "tech1", "tech2", "student1"))
    def mk(self, text="Projector not working"):
        return self.c.post("/api/tickets", json=dict(title=text, description=text, facility_id=4), headers=self.st).get_json()["id"]
    def act(self, h, tid, a, notes="n"):
        return self.c.post(f"/api/tickets/{tid}/transition", json={"action": a, "notes": notes}, headers=h)
    def test_full_lifecycle_and_authorisation(self):
        tid = self.mk()
        self.assertEqual(self.c.post(f"/api/tickets/{tid}/assign", json={"technician_id": 3}, headers=self.st).status_code, 403)
        self.assertEqual(self.c.post(f"/api/tickets/{tid}/assign", json={"technician_id": 3}, headers=self.fm).status_code, 200)
        self.assertEqual(self.act(self.t2, tid, "start_inspection").status_code, 403)       # not the assignee
        self.assertEqual(self.act(self.t1, tid, "resolve").status_code, 409)                # skipping inspection
        self.assertEqual(self.act(self.t1, tid, "start_inspection").get_json()["status"], "inspection")
        self.assertEqual(self.act(self.t1, tid, "request_work").get_json()["status"], "pending_work")
        self.assertEqual(self.act(self.t1, tid, "resolve").get_json()["status"], "resolved")
        self.assertEqual(self.act(self.t1, tid, "close").status_code, 403)                  # technician may not close
        self.assertEqual(self.act(self.fm, tid, "close", "").get_json()["status"], "closed")
        hist = self.c.get(f"/api/tickets/{tid}", headers=self.fm).get_json()["history"]
        self.assertEqual([h["action"] for h in hist][:3], ["ticket_created", "ticket_assigned", "ticket_start_inspection"])
    def test_sensor_dedup_and_threshold(self):
        ev = dict(sensor_id="S-1", event_id="E-1", facility_id=1, metric="temperature_c", value=35)
        r1 = self.c.post("/api/sensor-events", json=ev, headers=self.fm); r2 = self.c.post("/api/sensor-events", json=ev, headers=self.fm)
        self.assertEqual((r1.status_code, r2.status_code), (201, 200))
        self.assertTrue(r2.get_json()["duplicate"]); self.assertEqual(r1.get_json()["ticket_id"], r2.get_json()["ticket_id"])
        low = self.c.post("/api/sensor-events", json=dict(ev, event_id="E-2", value=22), headers=self.fm).get_json()
        self.assertIsNone(low["ticket_id"])
        self.assertEqual(len(self.c.get("/api/tickets", headers=self.fm).get_json()), 1)
    def test_sensor_intake_requires_role(self):
        ev = dict(sensor_id="S-1", event_id="E-9", facility_id=1, metric="power_kw", value=9)
        self.assertEqual(self.c.post("/api/sensor-events", json=ev, headers=self.st).status_code, 403)
    def test_audit_is_append_only(self):
        import sqlite3
        self.mk()
        from helpers import db
        _, path = make_client()
        c = db.connect(path)
        c.execute("INSERT INTO audit_events(ts,actor,action,entity_type,entity_id,details,instance_id) VALUES('t','a','x','y',1,'{}','i')")
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("UPDATE audit_events SET actor='evil'")
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("DELETE FROM audit_events")

if __name__ == "__main__":
    unittest.main()
