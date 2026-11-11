"""SQLite access. Each request gets its own connection; WAL lets two backend instances share one file."""
import sqlite3, json, datetime, os
from . import config

def utcnow():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def connect(path=None):
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    c = sqlite3.connect(path, timeout=10, isolation_level=None)   # autocommit; transactions are explicit
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA foreign_keys=ON"); c.execute("PRAGMA busy_timeout=8000")
    return c

def init_schema(c):
    with open(os.path.join(os.path.dirname(__file__), "schema.sql"), encoding="utf8") as f:
        c.executescript(f.read())
    for p, (r, s) in config.SLA_HOURS.items():
        c.execute("INSERT OR IGNORE INTO sla_policies VALUES(?,?,?)", (p, r, s))

def audit(c, actor, action, entity_type, entity_id, **details):
    c.execute("INSERT INTO audit_events(ts,actor,action,entity_type,entity_id,details,instance_id) VALUES(?,?,?,?,?,?,?)",
              (utcnow(), actor, action, entity_type, entity_id, json.dumps(details, sort_keys=True), config.INSTANCE_ID))
