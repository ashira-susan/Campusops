"""Two-instance experiments. Usage: python experiments.py --root <repo or worktree> --label v1.0.0 --out result.json
Starts two backend processes sharing ONE SQLite file (same topology as two containers on one volume)."""
import argparse, json, os, signal, statistics, subprocess, sys, tempfile, threading, time
import requests

PW = "exp-password"
def env_for(root, db, inst, port, work_ms):
    e = dict(os.environ, SECRET_KEY="experiment-secret", CAMPUSOPS_DB=db, INSTANCE_ID=inst, PORT=str(port),
             SIMULATED_WORK_MS=str(work_ms), SEED_PASSWORD=PW, HOST="127.0.0.1")
    return e

class Cluster:
    def __init__(self, root, work_ms=10):
        self.root, self.work_ms = root, work_ms
        self.dir = tempfile.mkdtemp(); self.db = os.path.join(self.dir, "exp.db"); self.procs = {}
        self.ports = {"A": 5101, "B": 5102}
        subprocess.run([sys.executable, "seed.py"], cwd=os.path.join(root, "backend"), env=env_for(root, self.db, "seed", 0, 0), check=True, capture_output=True)
    def start(self, which):
        p = subprocess.Popen([sys.executable, "run.py"], cwd=os.path.join(self.root, "backend"),
                             env=env_for(self.root, self.db, f"api-{which}", self.ports[which], self.work_ms), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs[which] = p
        for _ in range(100):
            try:
                if requests.get(self.url(which) + "/api/health", timeout=1).status_code == 200: return
            except requests.RequestException: time.sleep(0.1)
        raise RuntimeError("instance did not start")
    def url(self, which): return f"http://127.0.0.1:{self.ports[which]}"
    def kill(self, which):
        self.procs[which].send_signal(signal.SIGKILL); self.procs[which].wait()
    def stop(self):
        for p in self.procs.values():
            if p.poll() is None: p.terminate()
        for p in self.procs.values():
            try: p.wait(5)
            except Exception: p.kill()
    def tokens(self):
        t = {}
        for u in ("admin", "fm", "tech1", "tech2", "approver", "faculty1", "faculty2", "student1"):
            t[u] = {"Authorization": "Bearer " + requests.post(self.url("A") + "/api/login", json={"username": u, "password": PW}).json()["token"]}
        return t
    def sql(self, q, args=()):
        import sqlite3
        c = sqlite3.connect(self.db, timeout=10); r = c.execute(q, args).fetchall(); c.close(); return r

def par(fns):
    out = [None] * len(fns); bar = threading.Barrier(len(fns))
    def run(i):
        bar.wait(); out[i] = fns[i]()
    th = [threading.Thread(target=run, args=(i,)) for i in range(len(fns))]
    [t.start() for t in th]; [t.join() for t in th]; return out

def e1_overlap(cl, tk, rounds=60):
    wins = {0: 0, 1: 0, 2: 0}; codes = []
    for r in range(rounds):
        body = dict(facility_id=2 + r % 4, start_ts=f"2027-01-{1 + r // 4:02d}T09:00", end_ts=f"2027-01-{1 + r // 4:02d}T10:00", purpose=f"race {r}")
        res = par([lambda: requests.post(cl.url("A") + "/api/bookings", json=body, headers=tk["faculty1"]),
                   lambda: requests.post(cl.url("B") + "/api/bookings", json=body, headers=tk["faculty2"])])
        n = sum(x.status_code == 201 for x in res); wins[n] += 1; codes.append(sorted(x.status_code for x in res))
    pairs = cl.sql("""SELECT COUNT(*) FROM bookings a JOIN bookings b ON a.facility_id=b.facility_id AND a.id<b.id
                      AND a.start_ts<b.end_ts AND a.end_ts>b.start_ts
                      WHERE a.status IN ('requested','approved','confirmed','in_use') AND b.status IN ('requested','approved','confirmed','in_use')""")[0][0]
    return {"rounds": rounds, "rounds_with_both_accepted": wins[2], "rounds_with_one_accepted": wins[1], "rounds_with_none": wins[0],
            "overlapping_active_pairs_in_db": pairs, "response_pairs": {str(k): codes.count(list(k)) for k in {tuple(c) for c in codes}}}

def make_ticket_in_inspection(cl, tk):
    t = requests.post(cl.url("A") + "/api/tickets", json=dict(title="Projector not working", description="no image", facility_id=4), headers=tk["student1"]).json()["id"]
    requests.post(cl.url("A") + f"/api/tickets/{t}/assign", json={"technician_id": 3}, headers=tk["fm"])
    requests.post(cl.url("A") + f"/api/tickets/{t}/transition", json=dict(action="start_inspection", notes="looking"), headers=tk["tech1"])
    return t

def e2_ticket(cl, tk, rounds=40):
    both = one = anomalies = 0; finals = {}
    for r in range(rounds):
        t = make_ticket_in_inspection(cl, tk)
        v = requests.get(cl.url("A") + f"/api/tickets/{t}", headers=tk["tech1"]).json()["ticket"].get("version")   # None on v1.0
        mk = lambda act, note: dict(action=act, notes=note, **({"expected_version": v} if v is not None else {}))
        res = par([lambda: requests.post(cl.url("A") + f"/api/tickets/{t}/transition", json=mk("request_work", "needs spare part"), headers=tk["tech1"]),
                   lambda: requests.post(cl.url("B") + f"/api/tickets/{t}/transition", json=mk("resolve", "fixed on site"), headers=tk["admin"])])
        ok = sum(x.status_code == 200 for x in res)
        both += ok == 2; one += ok == 1
        hist = cl.sql("SELECT COUNT(*) FROM audit_events WHERE entity_type='ticket' AND entity_id=? AND action IN ('ticket_request_work','ticket_resolve')", (t,))[0][0]
        anomalies += hist == 2
        st = cl.sql("SELECT status FROM tickets WHERE id=?", (t,))[0][0]; finals[st] = finals.get(st, 0) + 1
    return {"rounds": rounds, "rounds_both_updates_accepted": both, "rounds_one_accepted_one_rejected": one,
            "rounds_with_two_conflicting_audit_events": anomalies, "final_status_distribution": finals}

def e3_retries(cl, tk, n=20):
    dup_seq = dup_conc = bk_replay_ok = 0
    for i in range(n):
        t = make_ticket_in_inspection(cl, tk)
        key = f"link-{i}-seq"
        requests.post(cl.url("A") + f"/api/tickets/{t}/devops-link", headers={**tk["fm"], "Idempotency-Key": key})      # response "lost"
        requests.post(cl.url("B") + f"/api/tickets/{t}/devops-link", headers={**tk["fm"], "Idempotency-Key": key})      # client retry
        dup_seq += cl.sql("SELECT COUNT(*) FROM integration_links WHERE ticket_id=?", (t,))[0][0] > 1
        t2 = make_ticket_in_inspection(cl, tk); key2 = f"link-{i}-conc"
        par([lambda: requests.post(cl.url("A") + f"/api/tickets/{t2}/devops-link", headers={**tk["fm"], "Idempotency-Key": key2}),
             lambda: requests.post(cl.url("B") + f"/api/tickets/{t2}/devops-link", headers={**tk["fm"], "Idempotency-Key": key2})])
        dup_conc += cl.sql("SELECT COUNT(*) FROM integration_links WHERE ticket_id=?", (t2,))[0][0] > 1
        body = dict(facility_id=2 + i % 4, start_ts=f"2027-02-{1 + i // 4:02d}T09:00", end_ts=f"2027-02-{1 + i // 4:02d}T10:00", purpose="retry")
        h = {**tk["faculty1"], "Idempotency-Key": f"bk-{i}"}
        r1 = requests.post(cl.url("A") + "/api/bookings", json=body, headers=h); r2 = requests.post(cl.url("B") + "/api/bookings", json=body, headers=h)
        bk_replay_ok += (r1.status_code == 201 and r2.status_code in (200, 201) and r2.json().get("id") == r1.json().get("id"))
    ev_dup = 0
    for i in range(n):
        ev = dict(sensor_id="S-X", event_id=f"E-{i}", facility_id=1, metric="temperature_c", value=40)
        par([lambda: requests.post(cl.url("A") + "/api/sensor-events", json=ev, headers=tk["fm"]), lambda: requests.post(cl.url("B") + "/api/sensor-events", json=ev, headers=tk["fm"])])
        ev_dup += cl.sql("SELECT COUNT(*) FROM tickets WHERE sensor_alert_id IN (SELECT id FROM sensor_alerts WHERE event_id=?)", (f"E-{i}",))[0][0] != 1
    return {"trials": n, "tickets_with_duplicate_links_sequential_retry": dup_seq, "tickets_with_duplicate_links_concurrent_retry": dup_conc,
            "booking_retry_returned_same_booking": bk_replay_ok, "sensor_events_with_duplicate_or_missing_ticket": ev_dup}

def e4_restart(cl, tk, seconds=8, workers=6):
    acked = []; lock = threading.Lock(); stop = threading.Event(); errors = [0]; i = [0]
    def worker(w):
        while not stop.is_set():
            with lock: i[0] += 1; k = i[0]
            body = dict(facility_id=2 + k % 4, start_ts=f"2028-{1 + k // 400:02d}-{1 + (k // 4) % 28:02d}T{8 + (k // 112) % 10:02d}:00", end_ts=f"2028-{1 + k // 400:02d}-{1 + (k // 4) % 28:02d}T{9 + (k // 112) % 10:02d}:00", purpose=f"load {k}")
            key = f"rs-{k}"
            for attempt in range(4):                      # client retries; alternates instance on failure
                inst = "AB"[(w + attempt) % 2]
                try:
                    r = requests.post(cl.url(inst) + "/api/bookings", json=body, headers={**tk["faculty1"], "Idempotency-Key": key}, timeout=3)
                    if r.status_code in (200, 201): 
                        with lock: acked.append((r.json()["id"], body["facility_id"], body["start_ts"]))
                    break
                except requests.RequestException:
                    errors[0] += 1; time.sleep(0.05)
    th = [threading.Thread(target=worker, args=(w,)) for w in range(workers)]
    [t.start() for t in th]; time.sleep(seconds * 0.35)
    cl.kill("A"); t_kill = time.time(); time.sleep(seconds * 0.3); cl.start("A"); time.sleep(seconds * 0.35); stop.set(); [t.join() for t in th]
    ids = [a[0] for a in acked]
    present = {r[0] for r in cl.sql("SELECT id FROM bookings")}
    missing = [x for x in ids if x not in present]
    no_audit = cl.sql("SELECT COUNT(*) FROM bookings b WHERE NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.entity_type='booking' AND a.entity_id=b.id AND a.action='booking_created')")[0][0]
    pairs = cl.sql("""SELECT COUNT(*) FROM bookings a JOIN bookings b ON a.facility_id=b.facility_id AND a.id<b.id AND a.start_ts<b.end_ts AND a.end_ts>b.start_ts
                      WHERE a.status<>'cancelled' AND b.status<>'cancelled'""")[0][0]
    orphan_requested = cl.sql("SELECT COUNT(*) FROM bookings WHERE status='approved' AND NOT EXISTS (SELECT 1 FROM audit_events a WHERE a.entity_type='booking' AND a.entity_id=bookings.id)")[0][0]
    return {"acknowledged_bookings": len(ids), "acknowledged_but_missing": len(missing), "bookings_without_audit_event": no_audit,
            "overlapping_pairs": pairs, "client_connection_errors_during_outage": errors[0], "unique_acknowledged_ids": len(set(ids))}

def e5_load(cl, tk, users, actions=3):
    lat = []; errs = {}; lock = threading.Lock(); users_list = ["faculty1", "faculty2", "student1", "fm"]
    def user(u):
        s = requests.Session(); h = tk[users_list[u % 4]]; inst = "AB"[u % 2]
        for a in range(actions):
            t0 = time.perf_counter()
            try:
                if a == 0: r = s.get(cl.url(inst) + "/api/dashboard", headers=h, timeout=60)
                elif a == 1: r = s.get(cl.url(inst) + "/api/tickets", headers=h, timeout=60)
                else:
                    k = u; r = s.post(cl.url(inst) + "/api/bookings", json=dict(facility_id=2 + k % 4, start_ts=f"{2029 + (users > 100)}-{1 + k // 100:02d}-{1 + (k // 4) % 25:02d}T09:00", end_ts=f"{2029 + (users > 100)}-{1 + k // 100:02d}-{1 + (k // 4) % 25:02d}T10:00", purpose="load"), headers={**h, "Idempotency-Key": f"ld-{users}-{u}"}, timeout=60)
                dt = time.perf_counter() - t0; code = r.status_code
            except requests.RequestException as e:
                dt = time.perf_counter() - t0; code = type(e).__name__
            with lock:
                lat.append(dt)
                if code not in (200, 201): errs[str(code)] = errs.get(str(code), 0) + 1
    t0 = time.perf_counter(); th = [threading.Thread(target=user, args=(u,)) for u in range(users)]
    [t.start() for t in th]; [t.join() for t in th]; wall = time.perf_counter() - t0
    lat.sort(); pct = lambda p: lat[min(len(lat) - 1, int(p * len(lat)))]
    return {"concurrent_users": users, "requests": len(lat), "wall_s": round(wall, 2), "throughput_rps": round(len(lat) / wall, 1),
            "p50_ms": round(pct(.5) * 1000), "p95_ms": round(pct(.95) * 1000), "max_ms": round(lat[-1] * 1000), "non_2xx": errs}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); ap.add_argument("--label", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="e1,e2,e3,e4,e5"); ap.add_argument("--work-ms", type=int, default=10)
    a = ap.parse_args(); result = {"label": a.label, "simulated_work_ms": a.work_ms, "cpu_count": os.cpu_count()}
    for name in a.only.split(","):
        cl = Cluster(a.root, a.work_ms); cl.start("A"); cl.start("B")
        try:
            tk = cl.tokens(); t0 = time.time()
            if name == "e1": result["e1_overlapping_reservations"] = e1_overlap(cl, tk)
            if name == "e2": result["e2_conflicting_ticket_updates"] = e2_ticket(cl, tk)
            if name == "e3": result["e3_duplicate_retries"] = e3_retries(cl, tk)
            if name == "e4": result["e4_instance_restart"] = e4_restart(cl, tk)
            if name == "e5": result["e5_load_60"] = e5_load(cl, tk, 60); result["e5_load_300"] = e5_load(cl, tk, 300)
            print(name, "done in", round(time.time() - t0, 1), "s", flush=True)
        finally:
            cl.stop()
    json.dump(result, open(a.out, "w"), indent=2); print(json.dumps(result, indent=2))
