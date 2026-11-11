from flask import Blueprint, g, jsonify, request
from .. import auth, config, db
from ..util import ApiError, require_fields

bp = Blueprint("core", __name__)

@bp.get("/api/health")
def health():
    g.db.execute("SELECT 1")
    return jsonify(status="ok", instance=config.INSTANCE_ID, integration_mode=config.INTEGRATION_MODE, version=VERSION)

@bp.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    require_fields(body, "username", "password")
    u = auth.authenticate(g.db, body["username"], body["password"])
    db.audit(g.db, u["username"], "login", "user", u["id"])
    return jsonify(token=auth.issue_token(u["id"]), user={"id": u["id"], "username": u["username"], "display_name": u["display_name"], "role": u["role"]})

@bp.get("/api/me")
@auth.login_required
def me():
    return jsonify(g.user)

@bp.get("/api/users")
@auth.login_required
def users():
    rows = g.db.execute("SELECT id,username,display_name,role FROM users ORDER BY id").fetchall()
    return jsonify([dict(r) for r in rows])

@bp.get("/api/facilities")
@auth.login_required
def facilities():
    rows = g.db.execute("SELECT * FROM facilities ORDER BY code").fetchall()
    return jsonify([dict(r) for r in rows])

@bp.get("/api/equipment")
@auth.login_required
def equipment():
    return jsonify([dict(r) for r in g.db.execute("SELECT * FROM equipment ORDER BY id")])

@bp.get("/api/audit")
@auth.roles_required("admin", "facility_manager", "approver")
def audit_log():
    et, eid = request.args.get("entity_type"), request.args.get("entity_id")
    q, args = "SELECT * FROM audit_events", []
    if et and eid:
        q += " WHERE entity_type=? AND entity_id=?"; args = [et, eid]
    q += " ORDER BY id DESC LIMIT 200"
    return jsonify([dict(r) for r in g.db.execute(q, args)])

VERSION = "dev"
