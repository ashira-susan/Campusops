"""Controlled sensor-event intake. Duplicate (sensor_id,event_id) pairs are rejected by a UNIQUE constraint."""
from flask import Blueprint, g, jsonify, request
import sqlite3
from .. import auth, config, db
from ..util import ApiError, require_fields
from .tickets import create_ticket, view

bp = Blueprint("sensors", __name__)

@bp.post("/api/sensor-events")
@auth.roles_required("admin", "facility_manager")
def sensor_event():
    body = request.get_json(silent=True) or {}
    require_fields(body, "sensor_id", "event_id", "facility_id", "metric", "value")
    if body["metric"] not in config.SENSOR_THRESHOLDS:
        raise ApiError(400, "unknown_metric", "metric must be one of " + ", ".join(config.SENSOR_THRESHOLDS))
    fac = g.db.execute("SELECT * FROM facilities WHERE id=?", (body["facility_id"],)).fetchone()
    if not fac:
        raise ApiError(404, "facility_not_found", "Unknown facility")
    try:
        value = float(body["value"])
    except (TypeError, ValueError):
        raise ApiError(400, "invalid_value", "value must be numeric")
    thr = config.SENSOR_THRESHOLDS[body["metric"]]
    try:
        cur = g.db.execute("INSERT INTO sensor_alerts(sensor_id,event_id,facility_id,metric,value,threshold,created_at) VALUES(?,?,?,?,?,?,?)",
                           (body["sensor_id"], body["event_id"], fac["id"], body["metric"], value, thr, db.utcnow()))
    except sqlite3.IntegrityError:
        a = g.db.execute("SELECT * FROM sensor_alerts WHERE sensor_id=? AND event_id=?", (body["sensor_id"], body["event_id"])).fetchone()
        return jsonify(duplicate=True, alert_id=a["id"], ticket_id=a["ticket_id"]), 200
    alert_id, ticket_id = cur.lastrowid, None
    db.audit(g.db, g.user["username"], "sensor_event_recorded", "sensor_alert", alert_id, metric=body["metric"], value=value, threshold=thr)
    if value >= thr:
        sensor = {"metric": body["metric"], "value": value, "threshold": thr}
        ticket_id = create_ticket(g.db, g.user, f"Sensor alert: {body['metric']} {value} at {fac['code']}",
                                  f"Sensor {body['sensor_id']} reported {body['metric']}={value} (threshold {thr}) at {fac['name']}",
                                  fac["id"], "sensor", alert_id, sensor)
        g.db.execute("UPDATE sensor_alerts SET ticket_id=? WHERE id=?", (ticket_id, alert_id))
    return jsonify(duplicate=False, alert_id=alert_id, ticket_id=ticket_id), 201
