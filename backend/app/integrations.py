"""Adapter for the external issue tracker. This release ships a SIMULATED tracker; the mode is always disclosed."""
from . import config

class IntegrationError(Exception):
    pass

def create_issue(ticket_id, existing_links, simulate_failure=False):
    if config.INTEGRATION_MODE != "simulated":
        raise IntegrationError("live integration is not configured in this release")
    if simulate_failure:
        raise IntegrationError("issue tracker unavailable (simulated timeout)")
    return {"system": "issue-tracker", "external_ref": f"CAMP-{ticket_id}-{existing_links + 1}", "mode": "simulated"}
