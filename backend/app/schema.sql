PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin','facility_manager','technician','approver','faculty','student')),
  password_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS facilities(
  id INTEGER PRIMARY KEY, code TEXT UNIQUE NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  capacity INTEGER NOT NULL, restricted INTEGER NOT NULL DEFAULT 0, campus TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equipment(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, facility_id INTEGER REFERENCES facilities(id));
CREATE TABLE IF NOT EXISTS sla_policies(
  priority TEXT PRIMARY KEY, response_hours INTEGER NOT NULL, resolution_hours INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS bookings(
  id INTEGER PRIMARY KEY, facility_id INTEGER NOT NULL REFERENCES facilities(id),
  requested_by INTEGER NOT NULL REFERENCES users(id), start_ts TEXT NOT NULL, end_ts TEXT NOT NULL,
  purpose TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('requested','approved','confirmed','in_use','completed','cancelled')),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, CHECK(end_ts > start_ts));
CREATE INDEX IF NOT EXISTS ix_bookings_fac_time ON bookings(facility_id, start_ts, end_ts);
CREATE TABLE IF NOT EXISTS sensor_alerts(
  id INTEGER PRIMARY KEY, sensor_id TEXT NOT NULL, event_id TEXT NOT NULL, facility_id INTEGER NOT NULL REFERENCES facilities(id),
  metric TEXT NOT NULL, value REAL NOT NULL, threshold REAL NOT NULL, ticket_id INTEGER, created_at TEXT NOT NULL,
  UNIQUE(sensor_id, event_id));
CREATE TABLE IF NOT EXISTS tickets(
  id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, facility_id INTEGER NOT NULL REFERENCES facilities(id),
  source TEXT NOT NULL CHECK(source IN ('manual','sensor')), sensor_alert_id INTEGER UNIQUE REFERENCES sensor_alerts(id),
  status TEXT NOT NULL CHECK(status IN ('intake','assigned','inspection','pending_work','resolved','closed')),
  category TEXT NOT NULL, priority TEXT NOT NULL, triage_explanation TEXT NOT NULL, suggested_category TEXT NOT NULL, suggested_priority TEXT NOT NULL,
  sla_due_at TEXT NOT NULL, assigned_to INTEGER REFERENCES users(id), inspection_notes TEXT, resolution_notes TEXT,
  created_by INTEGER REFERENCES users(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS approvals(
  id INTEGER PRIMARY KEY, subject_type TEXT NOT NULL CHECK(subject_type IN ('booking','equipment_loan')), subject_id INTEGER NOT NULL,
  requested_by INTEGER NOT NULL REFERENCES users(id), decided_by INTEGER REFERENCES users(id),
  decision TEXT NOT NULL DEFAULT 'pending' CHECK(decision IN ('pending','approved','rejected')), reason TEXT,
  created_at TEXT NOT NULL, decided_at TEXT, UNIQUE(subject_type, subject_id));
CREATE TABLE IF NOT EXISTS equipment_loans(
  id INTEGER PRIMARY KEY, equipment_id INTEGER NOT NULL REFERENCES equipment(id), requested_by INTEGER NOT NULL REFERENCES users(id),
  start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('requested','approved','rejected','returned')), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integration_links(
  id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id), system TEXT NOT NULL, external_ref TEXT NOT NULL,
  mode TEXT NOT NULL, delivery_status TEXT NOT NULL CHECK(delivery_status IN ('opened','in_progress','delivered')),
  verified_by INTEGER REFERENCES users(id), verified_at TEXT, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit_events(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, entity_type TEXT NOT NULL,
  entity_id INTEGER, details TEXT NOT NULL, instance_id TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_events BEGIN SELECT RAISE(ABORT,'audit_events is append-only'); END;
