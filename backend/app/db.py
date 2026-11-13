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

ACTIVE_SQL = "('requested','approved','confirmed','in_use')"

MIGRATION_1 = f"""
ALTER TABLE tickets ADD COLUMN version INTEGER NOT NULL DEFAULT 1;
CREATE TABLE IF NOT EXISTS idempotency_keys(
  key TEXT NOT NULL, user_id INTEGER NOT NULL, request_hash TEXT NOT NULL, status_code INTEGER NOT NULL,
  response_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(key, user_id));
CREATE UNIQUE INDEX IF NOT EXISTS ux_link_ticket_system ON integration_links(ticket_id, system);
CREATE TRIGGER IF NOT EXISTS bookings_no_overlap_ins BEFORE INSERT ON bookings
WHEN NEW.status IN {ACTIVE_SQL} AND EXISTS (SELECT 1 FROM bookings b WHERE b.facility_id=NEW.facility_id
     AND b.status IN {ACTIVE_SQL} AND b.start_ts < NEW.end_ts AND b.end_ts > NEW.start_ts)
BEGIN SELECT RAISE(ABORT,'booking_overlap'); END;
CREATE TRIGGER IF NOT EXISTS bookings_no_overlap_upd BEFORE UPDATE OF status,start_ts,end_ts,facility_id ON bookings
WHEN NEW.status IN {ACTIVE_SQL} AND EXISTS (SELECT 1 FROM bookings b WHERE b.id<>NEW.id AND b.facility_id=NEW.facility_id
     AND b.status IN {ACTIVE_SQL} AND b.start_ts < NEW.end_ts AND b.end_ts > NEW.start_ts)
BEGIN SELECT RAISE(ABORT,'booking_overlap'); END;
"""

def migrate(c):
    """Versioned, idempotent migrations tracked in PRAGMA user_version (safe to run from any instance start-up)."""
    if c.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    c.execute("BEGIN IMMEDIATE")
    try:
        if c.execute("PRAGMA user_version").fetchone()[0] < 1:
            removed = c.execute("""DELETE FROM integration_links WHERE id NOT IN
                                   (SELECT MIN(id) FROM integration_links GROUP BY ticket_id, system)""").rowcount
            if removed:
                audit(c, "migration", "migration_1_deduplicated_links", "integration_link", None, removed=removed)
            for stmt in [x.strip() for x in MIGRATION_1.split(";\n") if x.strip()]:
                c.execute(stmt + (";" if stmt.startswith("CREATE TRIGGER") else ""))
            c.execute("PRAGMA user_version = 1")
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK"); raise

def init_schema(c):
    with open(os.path.join(os.path.dirname(__file__), "schema.sql"), encoding="utf8") as f:
        c.executescript(f.read())
    for p, (r, s) in config.SLA_HOURS.items():
        c.execute("INSERT OR IGNORE INTO sla_policies VALUES(?,?,?)", (p, r, s))
    migrate(c)

def audit(c, actor, action, entity_type, entity_id, **details):
    c.execute("INSERT INTO audit_events(ts,actor,action,entity_type,entity_id,details,instance_id) VALUES(?,?,?,?,?,?,?)",
              (utcnow(), actor, action, entity_type, entity_id, json.dumps(details, sort_keys=True), config.INSTANCE_ID))
