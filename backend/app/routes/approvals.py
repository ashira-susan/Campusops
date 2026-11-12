"""Approvals (restricted-facility bookings, equipment loans) with separation of duties and mandatory justification."""
from flask import Blueprint, g, jsonify, request
from .. import auth, db
from ..util import ApiError, require_fields

bp = Blueprint("approvals", __name__)

@bp.get("/api/approvals")
@auth.roles_required("approver", "admin", "facility_manager")
def list_approvals():
    q = "SELECT a.*, u.display_name AS requester FROM approvals a JOIN users u ON u.id=a.requested_by"
    args = []
    if request.args.get("decision"):
        q += " WHERE a.decision=?"; args.append(request.args["decision"])
    return jsonify([dict(r) for r in g.db.execute(q + " ORDER BY a.id DESC", args)])

@bp.post("/api/approvals/<int:aid>/decide")
@auth.roles_required("approver")
def decide(aid):
    body = request.get_json(silent=True) or {}
    require_fields(body, "decision", "reason")
    if body["decision"] not in ("approved", "rejected"):
        raise ApiError(400, "invalid_decision", "decision must be approved or rejected")
    a = g.db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ApiError(404, "approval_not_found", "Unknown approval")
    if a["requested_by"] == g.user["id"]:
        raise ApiError(403, "separation_of_duties", "You cannot decide your own request")
    if a["decision"] != "pending":
        raise ApiError(409, "already_decided", f"Approval already {a['decision']}", decision=a["decision"])
    now = db.utcnow()
    g.db.execute("UPDATE approvals SET decision=?, decided_by=?, reason=?, decided_at=? WHERE id=?", (body["decision"], g.user["id"], body["reason"], now, aid))
    if a["subject_type"] == "booking":
        g.db.execute("UPDATE bookings SET status=?, updated_at=? WHERE id=?", ("approved" if body["decision"] == "approved" else "cancelled", now, a["subject_id"]))
    else:
        g.db.execute("UPDATE equipment_loans SET status=? WHERE id=?", (body["decision"], a["subject_id"]))
    db.audit(g.db, g.user["username"], f"approval_{body['decision']}", a["subject_type"], a["subject_id"], approval_id=aid, reason=body["reason"])
    return jsonify(dict(g.db.execute("SELECT * FROM approvals WHERE id=?", (aid,)).fetchone()))

@bp.get("/api/equipment-loans")
@auth.login_required
def loans():
    return jsonify([dict(r) for r in g.db.execute("SELECT l.*, e.name AS equipment FROM equipment_loans l JOIN equipment e ON e.id=l.equipment_id ORDER BY l.id DESC")])

@bp.post("/api/equipment-loans")
@auth.login_required
def create_loan():
    body = request.get_json(silent=True) or {}
    require_fields(body, "equipment_id", "start_date", "end_date")
    if body["end_date"] < body["start_date"]:
        raise ApiError(400, "invalid_interval", "end_date must not be before start_date")
    if not g.db.execute("SELECT 1 FROM equipment WHERE id=?", (body["equipment_id"],)).fetchone():
        raise ApiError(404, "equipment_not_found", "Unknown equipment")
    now = db.utcnow()
    cur = g.db.execute("INSERT INTO equipment_loans(equipment_id,requested_by,start_date,end_date,status,created_at) VALUES(?,?,?,?, 'requested',?)",
                       (body["equipment_id"], g.user["id"], body["start_date"], body["end_date"], now))
    g.db.execute("INSERT INTO approvals(subject_type,subject_id,requested_by,created_at) VALUES('equipment_loan',?,?,?)", (cur.lastrowid, g.user["id"], now))
    db.audit(g.db, g.user["username"], "loan_requested", "equipment_loan", cur.lastrowid)
    return jsonify(dict(g.db.execute("SELECT * FROM equipment_loans WHERE id=?", (cur.lastrowid,)).fetchone())), 201
