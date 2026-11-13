"""Cross-instance consistency tools. Correctness must not depend on in-process state, because two
backend instances share one database. SQLite's write lock (BEGIN IMMEDIATE) serialises writers from
every process; the overlap trigger and unique indexes are the last line of defence."""
import functools, hashlib, json
from flask import g, make_response, request
from . import db
from .util import ApiError

def transactional(fn):
    """Run the whole handler (checks + state change + audit event) as ONE atomic transaction."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        g.db.execute("BEGIN IMMEDIATE")
        try:
            result = fn(*a, **kw)
            g.db.execute("COMMIT")
            return result
        except ApiError as e:
            g.db.execute("COMMIT" if getattr(e, "commit", False) else "ROLLBACK")   # failure audits may be kept
            raise
        except BaseException:
            g.db.execute("ROLLBACK")
            raise
    return wrapper

def idempotent(fn):
    """Same Idempotency-Key + same request => stored response replayed, no second effect.
    Must sit INSIDE @transactional so the lookup and the insert happen under the write lock."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return fn(*a, **kw)
        digest = hashlib.sha256(json.dumps([request.method, request.path, g.user["id"], request.get_json(silent=True)], sort_keys=True).encode()).hexdigest()
        row = g.db.execute("SELECT * FROM idempotency_keys WHERE key=? AND user_id=?", (key, g.user["id"])).fetchone()
        if row:
            if row["request_hash"] != digest:
                raise ApiError(422, "idempotency_key_reuse", "This Idempotency-Key was already used with a different request")
            resp = make_response(row["response_json"], row["status_code"])
            resp.headers["Content-Type"] = "application/json"; resp.headers["Idempotent-Replay"] = "true"
            return resp
        resp = make_response(fn(*a, **kw))
        if 200 <= resp.status_code < 300:
            g.db.execute("INSERT INTO idempotency_keys(key,user_id,request_hash,status_code,response_json,created_at) VALUES(?,?,?,?,?,?)",
                         (key, g.user["id"], digest, resp.status_code, resp.get_data(as_text=True), db.utcnow()))
        return resp
    return wrapper
