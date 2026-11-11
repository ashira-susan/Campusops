import time, datetime
from . import config

class ApiError(Exception):
    def __init__(self, status, code, message, **extra):
        super().__init__(message); self.status, self.code, self.message, self.extra = status, code, message, extra

def simulated_work():
    """Stands in for validation/notification work (e.g. calendar sync). Duration is a documented assumption."""
    if config.SIMULATED_WORK_MS > 0:
        time.sleep(config.SIMULATED_WORK_MS / 1000.0)

def parse_ts(value, field):
    try:
        d = datetime.datetime.strptime(str(value), "%Y-%m-%dT%H:%M")
    except ValueError:
        raise ApiError(400, "invalid_timestamp", f"{field} must look like 2026-11-20T09:00")
    return d.strftime("%Y-%m-%dT%H:%M")

def require_fields(body, *names):
    missing = [n for n in names if body.get(n) in (None, "")]
    if missing:
        raise ApiError(400, "missing_fields", "Missing required field(s): " + ", ".join(missing), fields=missing)
