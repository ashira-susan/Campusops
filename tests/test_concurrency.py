"""Two Flask app objects on ONE database file emulate two backend instances; threads emulate simultaneous users."""
import os, sqlite3, threading, unittest, tempfile
from helpers import make_client, login, db, create_app, seedmod

def two_instances():
    c1, path = make_client(simulated_work_ms=5)
    c2 = create_app({"DB_PATH": path, "TESTING": True}).test_client()
    return c1, c2, path

def par(fns):
    out, bar = [None] * len(fns), threading.Barrier(len(fns))
    def run(i): bar.wait(); out[i] = fns[i]()
    th = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]; [t.start() for t in th]; [t.join() for t in th]; return out

class Concurrency(unittest.TestCase):
    def setUp(self):
        self.c1, self.c2, self.path = two_instances()
        self.f1, self.f2 = login(self.c1, "faculty1"), login(self.c1, "faculty2")
        self.fm, self.t1, self.ad = login(self.c1, "fm"), login(self.c1, "tech1"), login(self.c1, "admin")
    body = dict(facility_id=2, start_ts="2027-03-01T09:00", end_ts="2027-03-01T10:00", purpose="race")

    def test_overlap_exactly_one_winner_across_instances(self):
        for i in range(10):
            b = dict(self.body, start_ts=f"2027-03-{i+1:02d}T09:00", end_ts=f"2027-03-{i+1:02d}T10:00")
            r = par([lambda: self.c1.post("/api/bookings", json=b, headers=self.f1), lambda: self.c2.post("/api/bookings", json=b, headers=self.f2)])
            self.assertEqual(sorted(x.status_code for x in r), [201, 409])
    def test_database_trigger_blocks_overlap_even_if_application_check_is_bypassed(self):
        self.c1.post("/api/bookings", json=self.body, headers=self.f1)
        c = db.connect(self.path)
        with self.assertRaises(sqlite3.DatabaseError):
            c.execute("INSERT INTO bookings(facility_id,requested_by,start_ts,end_ts,purpose,status,created_at,updated_at) VALUES(2,1,'2027-03-01T09:30','2027-03-01T10:30','x','approved','t','t')")
    def test_idempotent_replay_and_key_reuse(self):
        h = {**self.f1, "Idempotency-Key": "k-1"}
        r1 = self.c1.post("/api/bookings", json=self.body, headers=h); r2 = self.c2.post("/api/bookings", json=self.body, headers=h)
        self.assertEqual((r1.status_code, r2.status_code), (201, 201)); self.assertEqual(r1.get_json()["id"], r2.get_json()["id"])
        self.assertEqual(r2.headers.get("Idempotent-Replay"), "true")
        r3 = self.c1.post("/api/bookings", json=dict(self.body, purpose="different"), headers=h)
        self.assertEqual(r3.status_code, 422)
    def test_concurrent_duplicate_requests_create_one_booking(self):
        h = {**self.f1, "Idempotency-Key": "k-dup"}
        r = par([lambda c=c: c.post("/api/bookings", json=self.body, headers=h) for c in (self.c1, self.c2, self.c1, self.c2)])
        self.assertEqual({x.get_json()["id"] for x in r}, {r[0].get_json()["id"]})
        self.assertEqual(db.connect(self.path).execute("SELECT COUNT(*) FROM bookings").fetchone()[0], 1)
    def _ticket(self):
        t = self.c1.post("/api/tickets", json=dict(title="Projector not working", description="x", facility_id=4), headers=self.f1).get_json()
        self.c1.post(f"/api/tickets/{t['id']}/assign", json=dict(technician_id=3, expected_version=t["version"]), headers=self.fm)
        v = self.c1.get(f"/api/tickets/{t['id']}", headers=self.fm).get_json()["ticket"]["version"]
        r = self.c1.post(f"/api/tickets/{t['id']}/transition", json=dict(action="start_inspection", notes="n", expected_version=v), headers=self.t1)
        return t["id"], r.get_json()["version"]
    def test_conflicting_ticket_updates_one_wins_one_stale(self):
        for _ in range(5):
            tid, v = self._ticket()
            r = par([lambda: self.c1.post(f"/api/tickets/{tid}/transition", json=dict(action="request_work", notes="part", expected_version=v), headers=self.t1),
                     lambda: self.c2.post(f"/api/tickets/{tid}/transition", json=dict(action="resolve", notes="fixed", expected_version=v), headers=self.ad)])
            self.assertEqual(sorted(x.status_code for x in r), [200, 409])
            self.assertEqual([x.get_json()["error"] for x in r if x.status_code == 409], ["version_conflict"])
            n = db.connect(self.path).execute("SELECT COUNT(*) FROM audit_events WHERE entity_type='ticket' AND entity_id=? AND action IN ('ticket_request_work','ticket_resolve')", (tid,)).fetchone()[0]
            self.assertEqual(n, 1)
    def test_missing_version_rejected(self):
        tid, v = self._ticket()
        r = self.c1.post(f"/api/tickets/{tid}/transition", json=dict(action="request_work", notes="x"), headers=self.t1)
        self.assertEqual((r.status_code, r.get_json()["error"]), (400, "version_required"))
    def test_double_approval_decision_one_winner(self):
        self.c1.post("/api/bookings", json=dict(self.body, facility_id=1), headers=self.f1)
        a = login(self.c1, "approver"); aid = self.c1.get("/api/approvals", headers=a).get_json()[0]["id"]
        r = par([lambda: self.c1.post(f"/api/approvals/{aid}/decide", json=dict(decision="approved", reason="ok"), headers=a),
                 lambda: self.c2.post(f"/api/approvals/{aid}/decide", json=dict(decision="rejected", reason="no"), headers=a)])
        self.assertEqual(sorted(x.status_code for x in r), [200, 409])
    def test_integration_failure_keeps_audit_and_writes_no_link(self):
        tid, _ = self._ticket()
        r = self.c1.post(f"/api/tickets/{tid}/devops-link", headers={**self.fm, "X-Simulate-Integration": "down", "Idempotency-Key": "i-1"})
        self.assertEqual(r.status_code, 502)
        con = db.connect(self.path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM integration_links").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM audit_events WHERE action='integration_failed'").fetchone()[0], 1)
        ok = self.c2.post(f"/api/tickets/{tid}/devops-link", headers={**self.fm, "Idempotency-Key": "i-1"})   # retry with same key succeeds
        self.assertEqual(ok.status_code, 201)
        again = self.c1.post(f"/api/tickets/{tid}/devops-link", headers={**self.fm, "Idempotency-Key": "i-1"})
        self.assertEqual(again.get_json()["id"], ok.get_json()["id"])
    def test_audit_written_atomically_with_state_change(self):
        self.c1.post("/api/bookings", json=self.body, headers=self.f1)
        con = db.connect(self.path)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM bookings b WHERE NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.entity_type='booking' AND a.entity_id=b.id)").fetchone()[0], 0)
    def test_migration_is_idempotent_and_removes_legacy_duplicate_links(self):
        path = os.path.join(tempfile.mkdtemp(), "legacy.db"); c = db.connect(path)
        with open(os.path.join(os.path.dirname(db.__file__), "schema.sql")) as f: c.executescript(f.read())   # v1.0-shaped DB
        seedmod.seed.__globals__["db"].init_schema  # noqa
        c.execute("INSERT INTO users(username,display_name,role,password_hash) VALUES('u','U','admin','x')")
        c.execute("INSERT INTO facilities(code,name,kind,capacity,restricted,campus) VALUES('F','F','room',1,0,'N')")
        c.execute("INSERT INTO tickets(title,description,facility_id,source,status,category,priority,triage_explanation,suggested_category,suggested_priority,sla_due_at,created_at,updated_at) VALUES('t','d',1,'manual','intake','other','P4','x','other','P4','x','x','x')")
        for i in range(2): c.execute("INSERT INTO integration_links(ticket_id,system,external_ref,mode,delivery_status,created_at) VALUES(1,'issue-tracker',?,'simulated','opened','t')", (f"R{i}",))
        db.migrate(c); db.migrate(c)
        self.assertEqual(c.execute("SELECT COUNT(*) FROM integration_links").fetchone()[0], 1)
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 1)

if __name__ == "__main__":
    unittest.main()
