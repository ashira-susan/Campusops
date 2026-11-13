"""Tickets. v1.1: every change is one transaction with optimistic version check (expected_version)."""
import datetime
from flask import Blueprint, g, jsonify, request
from .. import auth, config, db, triage
from ..util import ApiError, require_fields, simulated_work
from ..concurrency import transactional, idempotent

bp = Blueprint("tickets", __name__)
TRANSITIONS = {  # action -> (allowed from, to, roles; 'assignee' = the assigned technician)
    "start_inspection": (("assigned",), "inspection", ("assignee", "admin")),
    "request_work": (("inspection",), "pending_work", ("assignee", "admin")),
    "resolve": (("inspection", "pending_work"), "resolved", ("assignee", "admin")),
    "close": (("resolved",), "closed", ("facility_manager", "admin"))}

def _due(created_iso, priority):
    created = datetime.datetime.strptime(created_iso, "%Y-%m-%dT%H:%M:%SZ")
    return (created + datetime.timedelta(hours=config.SLA_HOURS[priority][1])).strftime("%Y-%m-%dT%H:%M:%SZ")

def sla_state(t):
    if t["status"] in ("resolved", "closed"):
        return {"state": "completed", "minutes_remaining": None}
    now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    due, created = datetime.datetime.strptime(t["sla_due_at"], fmt), datetime.datetime.strptime(t["created_at"], fmt)
    remaining = (due - now).total_seconds() / 60
    window = (due - created).total_seconds() / 60
    state = "breached" if remaining < 0 else ("at_risk" if remaining < 0.25 * window else "on_track")
    return {"state": state, "minutes_remaining": round(remaining)}

def view(r):
    d = dict(r); d["sla"] = sla_state(d); return d

def create_ticket(c, actor, title, description, facility_id, source, sensor_alert_id=None, sensor=None):
    sug = triage.suggest(f"{title}. {description}", sensor)
    now = db.utcnow()
    cur = c.execute("""INSERT INTO tickets(title,description,facility_id,source,sensor_alert_id,status,category,priority,triage_explanation,
                       suggested_category,suggested_priority,sla_due_at,created_by,created_at,updated_at) VALUES(?,?,?,?,?,'intake',?,?,?,?,?,?,?,?,?)""",
                    (title, description, facility_id, source, sensor_alert_id, sug["category"], sug["priority"], sug["explanation"],
                     sug["category"], sug["priority"], _due(now, sug["priority"]), actor["id"], now, now))
    db.audit(c, actor["username"], "ticket_created", "ticket", cur.lastrowid, source=source, category=sug["category"], priority=sug["priority"])
    return cur.lastrowid

@bp.get("/api/triage-preview")
@auth.login_required
def preview():
    return jsonify(triage.suggest(request.args.get("text", "")))

@bp.get("/api/tickets")
@auth.login_required
def list_tickets():
    q = ("SELECT t.*, f.code AS facility_code, a.display_name AS assignee FROM tickets t JOIN facilities f ON f.id=t.facility_id "
         "LEFT JOIN users a ON a.id=t.assigned_to WHERE 1=1")
    args = []
    if request.args.get("status"):
        q += " AND t.status=?"; args.append(request.args["status"])
    return jsonify([view(r) for r in g.db.execute(q + " ORDER BY t.priority, t.created_at", args)])

@bp.get("/api/tickets/<int:tid>")
@auth.login_required
def get_ticket(tid):
    t = g.db.execute("SELECT t.*, f.code AS facility_code, a.display_name AS assignee FROM tickets t JOIN facilities f ON f.id=t.facility_id "
                     "LEFT JOIN users a ON a.id=t.assigned_to WHERE t.id=?", (tid,)).fetchone()
    if not t:
        raise ApiError(404, "ticket_not_found", "Unknown ticket")
    links = [dict(r) for r in g.db.execute("SELECT * FROM integration_links WHERE ticket_id=?", (tid,))]
    hist = [dict(r) for r in g.db.execute("SELECT ts,actor,action,details,instance_id FROM audit_events WHERE entity_type='ticket' AND entity_id=? ORDER BY id", (tid,))]
    return jsonify(ticket=view(t), links=links, history=hist)

@bp.post("/api/tickets")
@auth.login_required
@transactional
@idempotent
def post_ticket():
    body = request.get_json(silent=True) or {}
    require_fields(body, "title", "description", "facility_id")
    if not g.db.execute("SELECT 1 FROM facilities WHERE id=?", (body["facility_id"],)).fetchone():
        raise ApiError(404, "facility_not_found", "Unknown facility")
    tid = create_ticket(g.db, g.user, body["title"], body["description"], body["facility_id"], "manual")
    return jsonify(view(g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone())), 201

def check_version(t, body):
    if body.get("expected_version") is None:
        raise ApiError(400, "version_required", "expected_version is required (read the ticket first)")
    if int(body["expected_version"]) != t["version"]:
        raise ApiError(409, "version_conflict", "Ticket was changed by someone else; reload and retry", current_version=t["version"], current_status=t["status"])

@bp.post("/api/tickets/<int:tid>/assign")
@auth.roles_required("facility_manager", "admin")
@transactional
def assign(tid):
    body = request.get_json(silent=True) or {}
    require_fields(body, "technician_id")
    t = g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ApiError(404, "ticket_not_found", "Unknown ticket")
    check_version(t, body)
    if t["status"] != "intake":
        raise ApiError(409, "invalid_transition", f"Cannot assign a ticket that is '{t['status']}'", current_status=t["status"])
    tech = g.db.execute("SELECT * FROM users WHERE id=? AND role='technician'", (body["technician_id"],)).fetchone()
    if not tech:
        raise ApiError(400, "invalid_technician", "technician_id must belong to a technician")
    cat = body.get("category") or t["category"]
    pri = body.get("priority") or t["priority"]
    if pri not in config.SLA_HOURS:
        raise ApiError(400, "invalid_priority", "priority must be P1..P4")
    g.db.execute("UPDATE tickets SET status='assigned', assigned_to=?, category=?, priority=?, sla_due_at=?, updated_at=?, version=version+1 WHERE id=?",
                 (tech["id"], cat, pri, _due(t["created_at"], pri), db.utcnow(), tid))
    db.audit(g.db, g.user["username"], "ticket_assigned", "ticket", tid, technician=tech["username"], category=cat, priority=pri,
             overrode_suggestion=(cat, pri) != (t["suggested_category"], t["suggested_priority"]))
    return jsonify(view(g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()))

@bp.post("/api/tickets/<int:tid>/transition")
@auth.login_required
@transactional
def ticket_transition(tid):
    body = request.get_json(silent=True) or {}
    require_fields(body, "action")
    spec = TRANSITIONS.get(body["action"])
    if not spec:
        raise ApiError(400, "unknown_action", "action must be one of " + ", ".join(TRANSITIONS))
    t = g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ApiError(404, "ticket_not_found", "Unknown ticket")
    frm, to, roles = spec
    check_version(t, body)
    ok = g.user["role"] in roles or ("assignee" in roles and t["assigned_to"] == g.user["id"])
    if not ok:
        raise ApiError(403, "forbidden", "You may not perform this action on this ticket")
    if t["status"] not in frm:
        raise ApiError(409, "invalid_transition", f"Cannot {body['action']} a ticket that is '{t['status']}'", current_status=t["status"])
    notes = body.get("notes", "")
    if body["action"] in ("start_inspection", "request_work", "resolve") and not notes:
        raise ApiError(400, "notes_required", "notes are required for this action")
    if body["action"] == "close":
        link = g.db.execute("SELECT * FROM integration_links WHERE ticket_id=? ORDER BY id DESC LIMIT 1", (tid,)).fetchone()
        if link and not (link["delivery_status"] == "delivered" and link["verified_at"]):
            raise ApiError(409, "delivery_not_verified", "Linked delivery is not verified as delivered; ticket cannot be closed")
    simulated_work()                                           # e.g. notify technician / sync calendar
    field = "resolution_notes" if body["action"] == "resolve" else "inspection_notes"
    sets, args = "status=?, updated_at=?, version=version+1", [to, db.utcnow()]
    if notes:
        sets += f", {field}=?"; args.append(notes)
    if to == "closed":
        sets += ", closed_at=?"; args.append(db.utcnow())
    cur = g.db.execute(f"UPDATE tickets SET {sets} WHERE id=? AND version=?", (*args, tid, t["version"]))
    if cur.rowcount != 1:                                  # defence in depth: the guarded UPDATE found a newer version
        raise ApiError(409, "version_conflict", "Ticket was changed by someone else; reload and retry")
    db.audit(g.db, g.user["username"], f"ticket_{body['action']}", "ticket", tid, frm=t["status"], to=to, notes=notes)
    return jsonify(view(g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()))
