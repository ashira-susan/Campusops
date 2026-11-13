import unittest
from helpers import make_client, login

class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.c, _ = make_client()
        self.s, self.ap, self.fm, self.t1 = (login(self.c, u) for u in ("student1", "approver", "fm", "tech1"))
    def test_restricted_booking_approve_and_authorisation(self):
        b = self.c.post("/api/bookings", json=dict(facility_id=1, start_ts="2026-11-21T09:00", end_ts="2026-11-21T10:00", purpose="practical"), headers=self.s).get_json()
        aid = self.c.get("/api/approvals?decision=pending", headers=self.ap).get_json()[0]["id"]
        self.assertEqual(self.c.post(f"/api/approvals/{aid}/decide", json=dict(decision="approved", reason="ok"), headers=self.s).status_code, 403)
        self.assertEqual(self.c.post(f"/api/approvals/{aid}/decide", json=dict(decision="approved"), headers=self.ap).status_code, 400)  # reason required
        r = self.c.post(f"/api/approvals/{aid}/decide", json=dict(decision="approved", reason="Supervised practical"), headers=self.ap)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/bookings", headers=self.s).get_json()[0]["status"], "approved")
        self.assertEqual(self.c.post(f"/api/approvals/{aid}/decide", json=dict(decision="rejected", reason="x"), headers=self.ap).status_code, 409)
    def test_rejection_cancels_and_frees_slot(self):
        self.c.post("/api/bookings", json=dict(facility_id=1, start_ts="2026-11-21T09:00", end_ts="2026-11-21T10:00", purpose="p"), headers=self.s)
        aid = self.c.get("/api/approvals", headers=self.ap).get_json()[0]["id"]
        self.c.post(f"/api/approvals/{aid}/decide", json=dict(decision="rejected", reason="not supervised"), headers=self.ap)
        r = self.c.post("/api/bookings", json=dict(facility_id=1, start_ts="2026-11-21T09:00", end_ts="2026-11-21T10:00", purpose="p2"), headers=self.s)
        self.assertEqual(r.status_code, 201)
    def test_devops_link_close_gate_and_failure_handling(self):
        tid = self.c.post("/api/tickets", json=dict(title="Projector not working", description="no image", facility_id=4), headers=self.s).get_json()["id"]
        ver = lambda: self.c.get(f"/api/tickets/{tid}", headers=self.fm).get_json()["ticket"]["version"]
        self.c.post(f"/api/tickets/{tid}/assign", json={"technician_id": 3, "expected_version": ver()}, headers=self.fm)
        for a in ("start_inspection", "resolve"):
            self.c.post(f"/api/tickets/{tid}/transition", json=dict(action=a, notes="n", expected_version=ver()), headers=self.t1)
        bad = self.c.post(f"/api/tickets/{tid}/devops-link", headers={**self.fm, "X-Simulate-Integration": "down"})
        self.assertEqual((bad.status_code, bad.get_json()["local_ticket_preserved"]), (502, True))
        link = self.c.post(f"/api/tickets/{tid}/devops-link", headers=self.fm).get_json()
        self.assertEqual(link["mode"], "simulated")
        close = lambda: self.c.post(f"/api/tickets/{tid}/transition", json={"action": "close", "expected_version": ver()}, headers=self.fm)
        self.assertEqual(close().status_code, 409)
        self.c.post(f"/api/integration-links/{link['id']}/progress", json={"delivery_status": "delivered"}, headers=self.fm)  # skip -> 409
        for st in ("in_progress", "delivered"):
            self.c.post(f"/api/integration-links/{link['id']}/progress", json={"delivery_status": st}, headers=self.fm)
        self.assertEqual(close().status_code, 409)                        # delivered but not verified
        self.c.post(f"/api/integration-links/{link['id']}/verify", headers=self.fm)
        self.assertEqual(close().get_json()["status"], "closed")

if __name__ == "__main__":
    unittest.main()
