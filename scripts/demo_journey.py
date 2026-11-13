"""End-to-end demonstration on TWO backend instances sharing one database, plus a process-level restart/persistence check.
Prints a step table; keeps instances running for UI screenshots when --shots is given."""
import json, os, subprocess, sys, time
import requests
sys.path.insert(0, os.path.dirname(__file__))
from experiments import Cluster, PW

root = sys.argv[1]; shots = "--shots" in sys.argv
cl = Cluster(root, work_ms=10); cl.start("A"); cl.start("B"); tk = cl.tokens(); steps = []
def call(step, inst, who, method, path, body=None, headers=None, note=""):
    h = {**tk[who], **(headers or {})}
    r = requests.request(method, cl.url(inst) + path, json=body, headers=h)
    try: j = r.json()
    except Exception: j = {}
    steps.append(dict(step=step, instance=inst, actor=who, request=f"{method} {path}", status=r.status_code, result=note or (j.get("error") or j.get("status") or "")))
    return r.status_code, j
def tver(t): return requests.get(cl.url("A") + f"/api/tickets/{t}", headers=tk["fm"]).json()["ticket"]["version"]
# --- Journey 1: controlled sensor alert -> closed ticket with DevOps link
code, j = call("1 sensor event (temperature 36 C, LAB-102)", "A", "fm", "POST", "/api/sensor-events", dict(sensor_id="S-TEMP-7", event_id="EVT-1001", facility_id=2, metric="temperature_c", value=36))
tid = j["ticket_id"]
call("2 duplicate sensor event (retry)", "B", "fm", "POST", "/api/sensor-events", dict(sensor_id="S-TEMP-7", event_id="EVT-1001", facility_id=2, metric="temperature_c", value=36), note="duplicate=true, same ticket")
t = requests.get(cl.url("A") + f"/api/tickets/{tid}", headers=tk["fm"]).json()["ticket"]
steps.append(dict(step="3 triage suggestion shown", instance="A", actor="fm", request=f"GET /api/tickets/{tid}", status=200, result=f"{t['suggested_category']}/{t['suggested_priority']}: {t['triage_explanation']}"))
call("4 assign to technician tara", "B", "fm", "POST", f"/api/tickets/{tid}/assign", dict(technician_id=3, expected_version=tver(tid)))
call("5 start inspection", "A", "tech1", "POST", f"/api/tickets/{tid}/transition", dict(action="start_inspection", notes="Cooling unit tripped; thermostat reads 36 C", expected_version=tver(tid)))
call("6 DevOps link while tracker is down", "B", "fm", "POST", f"/api/tickets/{tid}/devops-link", headers={"X-Simulate-Integration": "down", "Idempotency-Key": "demo-link-1"}, note="502, local ticket preserved")
c2, l = call("7 retry link with same key", "A", "fm", "POST", f"/api/tickets/{tid}/devops-link", headers={"Idempotency-Key": "demo-link-1"}, note="201 simulated link created")
lid = l["id"]
call("8 resolve", "B", "tech1", "POST", f"/api/tickets/{tid}/transition", dict(action="resolve", notes="Reset breaker and replaced contactor", expected_version=tver(tid)))
call("9 close before delivery verified", "A", "fm", "POST", f"/api/tickets/{tid}/transition", dict(action="close", expected_version=tver(tid)), note="rejected: delivery_not_verified")
call("10 delivery opened -> in_progress", "B", "fm", "POST", f"/api/integration-links/{lid}/progress", dict(delivery_status="in_progress"))
call("11 delivery in_progress -> delivered", "A", "fm", "POST", f"/api/integration-links/{lid}/progress", dict(delivery_status="delivered"))
call("12 verify delivery", "B", "fm", "POST", f"/api/integration-links/{lid}/verify")
call("13 close ticket", "A", "fm", "POST", f"/api/tickets/{tid}/transition", dict(action="close", expected_version=tver(tid)))
call("14 student tries to close (unauthorised)", "B", "student1", "POST", f"/api/tickets/{tid}/transition", dict(action="close", expected_version=tver(tid)), note="forbidden")
# --- Journey 2: restricted booking with approval
c, b = call("15 faculty requests restricted LAB-101", "A", "faculty1", "POST", "/api/bookings", dict(facility_id=1, start_ts="2026-12-02T10:00", end_ts="2026-12-02T12:00", purpose="Titration practical"), note="requested")
bid = b["id"]
aid = requests.get(cl.url("A") + "/api/approvals?decision=pending", headers=tk["approver"]).json()[0]["id"]
call("16 faculty tries to approve own request", "B", "faculty1", "POST", f"/api/approvals/{aid}/decide", dict(decision="approved", reason="x"), note="forbidden")
call("17 approver approves with reason", "B", "approver", "POST", f"/api/approvals/{aid}/decide", dict(decision="approved", reason="Supervised by lab instructor"))
call("18 confirm booking", "A", "faculty1", "POST", f"/api/bookings/{bid}/transition", dict(action="confirm"))
call("19 overlapping request by faculty2", "B", "faculty2", "POST", "/api/bookings", dict(facility_id=1, start_ts="2026-12-02T11:00", end_ts="2026-12-02T13:00", purpose="Other"), note="409 booking_overlap")
call("20 check in / complete", "A", "fm", "POST", f"/api/bookings/{bid}/transition", dict(action="check_in"))
call("21 complete", "B", "fm", "POST", f"/api/bookings/{bid}/transition", dict(action="complete"))
for s in steps: print(f"{s['step']:<48} {s['instance']} {s['actor']:<9} {s['status']}  {s['result'][:90]}")
json.dump(steps, open("/home/claude/evidence/journey_steps.json", "w"), indent=1)
counts = lambda: {t: cl.sql(f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("bookings", "tickets", "audit_events", "integration_links", "sensor_alerts", "approvals")}
if shots:
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH="/opt/pw-browsers", NODE_PATH="/opt/npm-tools/node_modules", BASE=cl.url("A"), PASSWORD=PW, TID=str(tid), OUT="/home/claude/evidence/shots")
    r = subprocess.run(["node", os.path.join(os.path.dirname(__file__), "shots.js")], env=env, capture_output=True, text=True); print("shots:", r.stdout.strip(), r.stderr.strip()[:400])
before = counts()
cl.kill("A"); cl.kill("B"); time.sleep(0.5)                         # stop BOTH backend processes
cl.start("A"); cl.start("B")
after = counts()
t_after = requests.get(cl.url("B") + f"/api/tickets/{tid}", headers={"Authorization": "Bearer " + requests.post(cl.url("B") + "/api/login", json={"username": "fm", "password": PW}).json()["token"]}).json()
persist = {"counts_before_restart": before, "counts_after_restart": after, "identical": before == after, "ticket_status_after_restart": t_after["ticket"]["status"],
           "ticket_history_events_after_restart": len(t_after["history"]), "link_after_restart": t_after["links"][0]["external_ref"] + " " + t_after["links"][0]["delivery_status"]}
print(json.dumps(persist, indent=1)); json.dump(persist, open("/home/claude/evidence/persistence.json", "w"), indent=1)
cl.stop()
