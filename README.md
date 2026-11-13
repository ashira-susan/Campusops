# CampusOps – Smart Campus Facility Booking & Maintenance Platform

Course: CSA10 Software Engineering – Assignment 3 (CO3).
First-release scope: facility booking, sensor-alert intake, rule-based triage,
technician assignment, inspection, approval and verified closure.

See `docs/` for design notes. Stack: Flask + SQLite (WAL) + vanilla JS, Docker Compose.

## Run (clean environment)
```
cp .env.example .env          # then edit the placeholder values
docker compose up --build -d     # init (migrate+seed) -> api1, api2 -> nginx on :8080
open http://localhost:8080    # sign in as admin / fm / tech1 / approver / student1 with SEED_PASSWORD
docker compose down           # data persists in the named volume; add -v to wipe it
```
Without Docker: `pip install -r backend/requirements.txt`, export the variables from `.env`, `python backend/seed.py && python backend/run.py`.

## Tests
`cd tests && python -m unittest discover`

## Known limitations (v1.1.0)
- SQLite on a shared volume is only valid for several instances on **one Docker host**; use PostgreSQL before multi-host deployment.
- The simulated 10 ms calendar sync runs inside the database write lock, which caps write throughput.
- Werkzeug's threaded server is used instead of gunicorn (that is what was load-tested).
- Triage is keyword rules, not machine learning; the issue-tracker link is simulated (mode shown in the UI).
- Single ticket assignee; no password reset, TLS termination or rate limiting.
