"""Serves the trained close-probability model. Standard library only.

Loads data/model.json (written by training/train.py). If that file is missing, or was built from
synthetic demo data, load() returns None and Deal Radar falls back to the hand-written rules.
"""
import json
import math
import os

import features as F

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "data", "model.json")


def load(path=PATH):
    if not os.path.exists(path):
        return None
    with open(path) as f:
        m = json.load(f)
    if m.get("demo") and not os.environ.get("ALLOW_DEMO_MODEL"):
        return None
    if m.get("features") != F.FEATURES:
        return None   # features.py changed since training: retrain rather than score with stale weights
    return m


def _sig(z):
    return 1 / (1 + math.exp(-z))


def predict(model, row):
    """Return (p_close, drivers). Drivers use the same shape as the rules in terms.py: label, delta, note."""
    z = model["intercept"]
    parts = []
    for name, mu, sd, w in zip(model["features"], model["mean"], model["scale"], model["coef"]):
        c = w * ((row.get(name, 0.0) - mu) / (sd or 1.0))
        z += c
        parts.append((name, c, row.get(name, 0.0)))
    p = _sig(z)
    drivers = [{"label": "Typical announced deal in the training data", "delta": 0.0,
                "note": "%.0f%% of %d past deals closed." % (100 * model["close_rate"], model["n_deals"])}]
    # Show the features that moved this deal most, in probability points
    base = z
    for name, c, v in sorted(parts, key=lambda t: -abs(t[1]))[:6]:
        if abs(c) < 0.03 or name == "log_len" or not v:
            continue   # only explain with things that are actually present in this filing
        delta = _sig(base) - _sig(base - c)
        drivers.append({"label": F.LABELS.get(name, name), "delta": round(delta, 3),
                        "note": "Learned from past deals: this shifts the odds " + ("up" if c > 0 else "down") + "."})
    return p, drivers


def timing_curve(model, row, flags_group=None):
    """Cumulative chance a deal like this has been decided by day d after announcement."""
    g = "tender" if row.get("tender") else "second_request" if row.get("second_request") else "vote" if row.get("vote") else "other"
    return model["timing"].get(g) or model["timing"].get("all")


def resolved_by(curve, elapsed_days, extra_days):
    """P(decided within extra_days from now | not decided yet after elapsed_days)."""
    def F_(d):
        if d <= curve[0][0]:
            return curve[0][1]
        for (d0, p0), (d1, p1) in zip(curve, curve[1:]):
            if d <= d1:
                return p0 + (p1 - p0) * (d - d0) / (d1 - d0)
        return curve[-1][1]
    now = F_(elapsed_days)
    if now >= 0.999:
        return 0.97
    return min(0.97, max(0.03, (F_(elapsed_days + extra_days) - now) / (1 - now)))
