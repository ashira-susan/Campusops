from flask import Blueprint, g, jsonify
from .. import auth
from .tickets import sla_state

bp = Blueprint("dashboard", __name__)

@bp.get("/api/dashboard")
@auth.login_required
def dashboard():
    c = g.db
    by_status = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM tickets GROUP BY status")}
    open_t = [dict(r) for r in c.execute("SELECT * FROM tickets WHERE status NOT IN ('resolved','closed')")]
    sla = {"on_track": 0, "at_risk": 0, "breached": 0}
    for t in open_t:
        sla[sla_state(t)["state"]] += 1
    bookings = {r["status"]: r["n"] for r in c.execute("SELECT status, COUNT(*) n FROM bookings GROUP BY status")}
    alerts = c.execute("SELECT COUNT(*) FROM sensor_alerts").fetchone()[0]
    pending = c.execute("SELECT COUNT(*) FROM approvals WHERE decision='pending'").fetchone()[0]
    return jsonify(tickets_by_status=by_status, open_ticket_sla=sla, bookings_by_status=bookings,
                   sensor_alerts=alerts, pending_approvals=pending,
                   note="Illustrative counts from synthetic data; not production monitoring.")
