# CampusOps – Smart Campus Facility Booking & Maintenance Platform

Course: CSA10 Software Engineering – Assignment 3 (CO3).
First-release scope: facility booking, sensor-alert intake, rule-based triage,
technician assignment, inspection, approval and verified closure.

See `docs/` for design notes. Stack: Flask + SQLite (WAL) + vanilla JS, Docker Compose.

## Run (clean environment)
```
cp .env.example .env          # then edit the placeholder values
docker compose up --build -d
open http://localhost:8080    # sign in as admin / fm / tech1 / approver / student1 with SEED_PASSWORD
docker compose down           # data persists in the named volume; add -v to wipe it
```
Without Docker: `pip install -r backend/requirements.txt`, export the variables from `.env`, `python backend/seed.py && python backend/run.py`.

## Tests
`cd tests && python -m unittest discover`
