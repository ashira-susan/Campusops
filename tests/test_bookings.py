import unittest
from helpers import make_client, login

class BookingTests(unittest.TestCase):
    def setUp(self):
        self.c, self.path = make_client()
        self.s, self.f, self.a = login(self.c, "student1"), login(self.c, "faculty1"), login(self.c, "approver")
    def book(self, h, fac=2, s="2026-11-20T09:00", e="2026-11-20T11:00", **kw):
        return self.c.post("/api/bookings", json=dict(facility_id=fac, start_ts=s, end_ts=e, purpose="lecture"), headers=h)
    def test_unauthenticated_rejected(self):
        self.assertEqual(self.c.get("/api/facilities").status_code, 401)
    def test_unrestricted_booking_auto_approved(self):
        r = self.book(self.s); self.assertEqual((r.status_code, r.get_json()["status"]), (201, "approved"))
    def test_restricted_booking_needs_approval(self):
        r = self.book(self.s, fac=1); self.assertEqual(r.get_json()["status"], "requested")
    def test_overlap_rejected_adjacent_allowed(self):
        self.assertEqual(self.book(self.s).status_code, 201)
        self.assertEqual(self.book(self.f, s="2026-11-20T10:00", e="2026-11-20T12:00").status_code, 409)
        self.assertEqual(self.book(self.f, s="2026-11-20T11:00", e="2026-11-20T12:00").status_code, 201)
    def test_invalid_interval(self):
        self.assertEqual(self.book(self.s, s="2026-11-20T11:00", e="2026-11-20T09:00").status_code, 400)
    def test_booking_lifecycle_and_invalid_transition(self):
        bid = self.book(self.s).get_json()["id"]
        t = lambda h, a: self.c.post(f"/api/bookings/{bid}/transition", json={"action": a}, headers=h)
        self.assertEqual(t(self.s, "confirm").get_json()["status"], "confirmed")
        self.assertEqual(t(self.s, "complete").status_code, 403)          # requester may not complete
        fm = login(self.c, "fm")
        self.assertEqual(t(fm, "complete").status_code, 409)              # not in_use yet
        self.assertEqual(t(fm, "check_in").get_json()["status"], "in_use")
        self.assertEqual(t(fm, "complete").get_json()["status"], "completed")
    def test_cancelled_slot_is_reusable(self):
        bid = self.book(self.s).get_json()["id"]
        self.c.post(f"/api/bookings/{bid}/transition", json={"action": "cancel"}, headers=self.s)
        self.assertEqual(self.book(self.f).status_code, 201)

if __name__ == "__main__":
    unittest.main()
