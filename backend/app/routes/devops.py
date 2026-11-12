"""Link a maintenance ticket to a developer issue / delivery status. Mode (simulated|live) is always disclosed."""
from flask import Blueprint, g, jsonify, request
from .. import auth, db, integrations
from ..util import ApiError, require_fields

bp = Blueprint("devops", __name__)
ORDER = ["opened", "in_progress", "delivered"]

@bp.post("/api/tickets/<int:tid>/devops-link")
@auth.roles_required("facility_manager", "admin")
def create_link(tid):
    t = g.db.execute("SELECT * FROM tickets WHERE id=?", (tid,)).fetchone()
    if not t:
        raise ApiError(404, "ticket_not_found", "Unknown ticket")
    n = g.db.execute("SELECT COUNT(*) FROM integration_links WHERE ticket_id=?", (tid,)).fetchone()[0]
    try:
        issue = integrations.create_issue(tid, n, simulate_failure=request.headers.get("X-Simulate-Integration") == "down")
    except integrations.IntegrationError as e:
        db.audit(g.db, g.user["username"], "integration_failed", "ticket", tid, error=str(e))
        raise ApiError(502, "integration_unavailable", str(e), local_ticket_preserved=True, retry_safe=True)
    cur = g.db.execute("INSERT INTO integration_links(ticket_id,system,external_ref,mode,delivery_status,created_at) VALUES(?,?,?,?, 'opened',?)",
                       (tid, issue["system"], issue["external_ref"], issue["mode"], db.utcnow()))
    db.audit(g.db, g.user["username"], "integration_linked", "ticket", tid, ref=issue["external_ref"], mode=issue["mode"])
    return jsonify(dict(g.db.execute("SELECT * FROM integration_links WHERE id=?", (cur.lastrowid,)).fetchone())), 201

@bp.post("/api/integration-links/<int:lid>/progress")
@auth.roles_required("facility_manager", "admin")
def progress(lid):
    body = request.get_json(silent=True) or {}
    require_fields(body, "delivery_status")
    link = g.db.execute("SELECT * FROM integration_links WHERE id=?", (lid,)).fetchone()
    if not link:
        raise ApiError(404, "link_not_found", "Unknown link")
    new = body["delivery_status"]
    if new not in ORDER or ORDER.index(new) != ORDER.index(link["delivery_status"]) + 1:
        raise ApiError(409, "invalid_transition", f"Cannot move delivery from '{link['delivery_status']}' to '{new}'")
    g.db.execute("UPDATE integration_links SET delivery_status=? WHERE id=?", (new, lid))
    db.audit(g.db, g.user["username"], "delivery_progress", "ticket", link["ticket_id"], link=lid, to=new, mode=link["mode"])
    return jsonify(dict(g.db.execute("SELECT * FROM integration_links WHERE id=?", (lid,)).fetchone()))

@bp.post("/api/integration-links/<int:lid>/verify")
@auth.roles_required("facility_manager", "admin")
def verify(lid):
    link = g.db.execute("SELECT * FROM integration_links WHERE id=?", (lid,)).fetchone()
    if not link:
        raise ApiError(404, "link_not_found", "Unknown link")
    if link["delivery_status"] != "delivered":
        raise ApiError(409, "not_delivered", "Only a delivered item can be verified")
    g.db.execute("UPDATE integration_links SET verified_by=?, verified_at=? WHERE id=?", (g.user["id"], db.utcnow(), lid))
    db.audit(g.db, g.user["username"], "delivery_verified", "ticket", link["ticket_id"], link=lid)
    return jsonify(dict(g.db.execute("SELECT * FROM integration_links WHERE id=?", (lid,)).fetchone()))
