"""Bookings. v1.0 assumes ONE backend process: overlap is guarded by an in-process lock."""
import threading
from flask import Blueprint, g, jsonify, request
from .. import auth, db
from ..util import ApiError, parse_ts, require_fields, simulated_work

bp = Blueprint("bookings", __name__)
ACTIVE = ("requested", "approved", "confirmed", "in_use")
# action -> (from_status, to_status, roles allowed besides the requester, requester allowed?)
ACTIONS = {"confirm": ("approved", "confirmed", ("facility_manager", "admin"), True),
           "check_in": ("confirmed", "in_use", ("facility_manager", "technician", "admin"), False),
           "complete": ("in_use", "completed", ("facility_manager", "technician", "admin"), False),
           "cancel": (("requested", "approved", "confirmed"), "cancelled", ("facility_manager", "admin"), True)}
_lock = threading.Lock()

def overlap(c, facility_id, start, end, exclude_id=None):
    q = (f"SELECT id FROM bookings WHERE facility_id=? AND status IN ({','.join('?'*len(ACTIVE))}) "
         "AND start_ts < ? AND end_ts > ?")
    args = [facility_id, *ACTIVE, end, start]
    if exclude_id:
        q += " AND id<>?"; args.append(exclude_id)
    return c.execute(q, args).fetchone()

def row(r):
    return dict(r)

@bp.get("/api/bookings")
@auth.login_required
def list_bookings():
    q, args = ("SELECT b.*, f.code AS facility_code, u.display_name AS requester FROM bookings b "
               "JOIN facilities f ON f.id=b.facility_id JOIN users u ON u.id=b.requested_by WHERE 1=1"), []
    if request.args.get("facility_id"):
        q += " AND b.facility_id=?"; args.append(request.args["facility_id"])
    if request.args.get("date"):
        q += " AND substr(b.start_ts,1,10)=?"; args.append(request.args["date"])
    return jsonify([row(r) for r in g.db.execute(q + " ORDER BY b.start_ts", args)])

@bp.post("/api/bookings")
@auth.login_required
def create_booking():
    body = request.get_json(silent=True) or {}
    require_fields(body, "facility_id", "start_ts", "end_ts", "purpose")
    start, end = parse_ts(body["start_ts"], "start_ts"), parse_ts(body["end_ts"], "end_ts")
    if end <= start:
        raise ApiError(400, "invalid_interval", "end_ts must be after start_ts")
    fac = g.db.execute("SELECT * FROM facilities WHERE id=?", (body["facility_id"],)).fetchone()
    if not fac:
        raise ApiError(404, "facility_not_found", "Unknown facility")
    status = "requested" if fac["restricted"] else "approved"
    now = db.utcnow()
    with _lock:                                            # protects THIS process only
        hit = overlap(g.db, fac["id"], start, end)
        if hit:
            raise ApiError(409, "booking_overlap", "Facility already booked for an overlapping slot", conflicting_booking=hit["id"])
        simulated_work()                                   # e.g. external calendar sync
        cur = g.db.execute("INSERT INTO bookings(facility_id,requested_by,start_ts,end_ts,purpose,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                           (fac["id"], g.user["id"], start, end, body["purpose"], status, now, now))
    bid = cur.lastrowid
    if fac["restricted"]:
        g.db.execute("INSERT INTO approvals(subject_type,subject_id,requested_by,created_at) VALUES('booking',?,?,?)", (bid, g.user["id"], now))
    db.audit(g.db, g.user["username"], "booking_created", "booking", bid, status=status, facility=fac["code"], start=start, end=end)
    return jsonify(row(g.db.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone())), 201

@bp.post("/api/bookings/<int:bid>/transition")
@auth.login_required
def transition(bid):
    body = request.get_json(silent=True) or {}
    require_fields(body, "action")
    spec = ACTIONS.get(body["action"])
    if not spec:
        raise ApiError(400, "unknown_action", "action must be one of " + ", ".join(ACTIONS))
    b = g.db.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()
    if not b:
        raise ApiError(404, "booking_not_found", "Unknown booking")
    frm, to, roles, requester_ok = spec
    allowed = g.user["role"] in roles or (requester_ok and b["requested_by"] == g.user["id"])
    if not allowed:
        raise ApiError(403, "forbidden", "You may not perform this action on this booking")
    frm = (frm,) if isinstance(frm, str) else frm
    if b["status"] not in frm:
        raise ApiError(409, "invalid_transition", f"Cannot {body['action']} a booking that is '{b['status']}'", current_status=b["status"])
    g.db.execute("UPDATE bookings SET status=?, updated_at=? WHERE id=?", (to, db.utcnow(), bid))
    db.audit(g.db, g.user["username"], f"booking_{body['action']}", "booking", bid, frm=b["status"], to=to)
    return jsonify(row(g.db.execute("SELECT * FROM bookings WHERE id=?", (bid,)).fetchone()))
