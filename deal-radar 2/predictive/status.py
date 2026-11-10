"""What the interface is allowed to say about the research models."""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "predictive", "manifest.json")


def public_status():
    """A short status for the page. It never invents a probability."""
    if not os.path.exists(MANIFEST):
        return {
            "trained": False,
            "reason": "No point-in-time acquisition model has been trained.",
        }
    with open(MANIFEST, encoding="utf-8") as handle:
        manifest = json.load(handle)
    trained = bool(manifest.get("trained"))
    status = {
        "trained": trained,
        "reason": manifest.get("reason") or "No point-in-time acquisition model has been trained.",
        "counts": manifest.get("counts") or {},
    }
    if not trained:
        return status
    # A future trained manifest may name its file. Probabilities are not copied
    # onto the company list from this status call.
    status["modelFile"] = manifest.get("modelFile")
    return status
