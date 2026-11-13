"""Central configuration. Secrets come from the environment, never from source code."""
import os

DB_PATH = os.environ.get("CAMPUSOPS_DB", "data/campusops.db")
INSTANCE_ID = os.environ.get("INSTANCE_ID", "local")
# Planning assumption (documented in the report): validation/notification work per write, in ms.
SIMULATED_WORK_MS = int(os.environ.get("SIMULATED_WORK_MS", "10"))
INTEGRATION_MODE = os.environ.get("INTEGRATION_MODE", "simulated")   # "simulated" | "live"
TOKEN_MAX_AGE_S = 8 * 3600

# Controlled sensor thresholds (assumption): an event at/above the value raises a ticket.
SENSOR_THRESHOLDS = {"temperature_c": 30.0, "humidity_pct": 70.0, "power_kw": 8.0, "water_leak": 1.0}

# SLA policy in hours: priority -> (response, resolution). Planning assumption.
def _hours(name, default):
    return int(os.environ.get(name, default))

# P1 resolution default is 2 h (from feature/sla-strict-p1); every value can be overridden by environment variable.
SLA_HOURS = {p: (_hours(f"SLA_{p}_RESPONSE_H", r), _hours(f"SLA_{p}_RESOLUTION_H", s))
             for p, (r, s) in {"P1": (1, 2), "P2": (2, 8), "P3": (4, 24), "P4": (8, 72)}.items()}

ROLES = ("admin", "facility_manager", "technician", "approver", "faculty", "student")
