"""Deterministic, explainable triage. This is a KEYWORD RULE SET, not a trained ML model:
the same text always gives the same suggestion, and a human confirms the final category/priority."""
import re

CATEGORY_KEYWORDS = {
    "safety": ["smoke", "fire", "gas", "spark", "sparks", "shock", "burning", "alarm", "injury"],
    "electrical": ["power", "electric", "socket", "voltage", "outage", "circuit", "tripped", "light", "lights", "lighting"],
    "hvac": ["air conditioner", "hvac", "temperature", "heating", "ventilation", "humidity", "hot", "cold", " ac "],
    "plumbing": ["leak", "leaking", "water", "pipe", "tap", "flood", "drain", "toilet"],
    "it_network": ["wifi", "network", "projector", "internet", "router", "computer", "display", "screen"],
    "structural": ["ceiling", "crack", "door", "window", "wall", "floor", "lock"],
}
FAILURE_WORDS = ["not working", "broken", "fault", "failed", "failure", "down", "outage", "stopped", "dead"]
URGENT_WORDS = ["urgent", "emergency", "immediately", "exam"]

def suggest(text, sensor=None):
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    hits = {cat: [k for k in kws if k in t] for cat, kws in CATEGORY_KEYWORDS.items()}
    hits = {c: h for c, h in hits.items() if h}
    why = []
    if sensor:                                      # sensor events carry their own category
        category = {"temperature_c": "hvac", "humidity_pct": "hvac", "power_kw": "electrical", "water_leak": "plumbing"}.get(sensor["metric"], "other")
        why.append(f"sensor metric '{sensor['metric']}' mapped to category '{category}'")
    elif hits:
        category = max(hits, key=lambda c: (c == "safety", len(hits[c]), -list(CATEGORY_KEYWORDS).index(c)))
        why.append(f"keywords {hits[category]} matched category '{category}'")
    else:
        category = "other"; why.append("no category keyword matched, defaulted to 'other'")
    failure = [w for w in FAILURE_WORDS if w in t]
    urgent = [w for w in URGENT_WORDS if w in t]
    if "safety" in hits:
        priority = "P1"; why.append("rule R1: safety keyword present -> P1")
    elif sensor and sensor["value"] >= 1.5 * sensor["threshold"]:
        priority = "P1"; why.append(f"rule R2: sensor value {sensor['value']} is >= 1.5 x threshold {sensor['threshold']} -> P1")
    elif sensor or (failure and category in ("electrical", "hvac", "plumbing", "it_network")) or urgent:
        priority = "P2"; why.append("rule R3: sensor breach, service failure in a core category, or urgent wording -> P2")
    elif failure:
        priority = "P3"; why.append(f"rule R4: failure wording {failure} -> P3")
    else:
        priority = "P4"; why.append("rule R5: no failure or urgency wording -> P4")
    return {"category": category, "priority": priority, "explanation": "; ".join(why),
            "method": "keyword rules (deterministic, not machine learning)"}
