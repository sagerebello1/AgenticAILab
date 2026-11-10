"""Hand a validated acquisition probability to the Black-Scholes scenario.

This module does not estimate a probability by itself, and it does not read the
announced-deal closing rule. A missing or rejected probability stays missing.
"""
import black_scholes


def supply_decision(audit, validation, holdout):
    """Whether a holdout result may be used as an option-valuation probability.

    Beating a base rate inside a case-control extract is not enough. The sample
    also has to be a market-wide draw, with no look-ahead, and the same
    improvement has to show on the validation fold and on the later holdout.
    """
    reasons = []
    if audit.get("feature_lookahead_violations", 1) != 0:
        reasons.append("A feature used information from after the prediction date.")
    if not audit.get("market_wide_sample"):
        reasons.append(audit.get("market_wide_reason") or "The sample is not a market-wide draw of companies.")
    for label, block in (("validation", validation), ("holdout", holdout)):
        if not block or block.get("pr_auc") is None or block.get("base_pr_auc") is None:
            reasons.append("The %s precision-recall score was not computed." % label)
            continue
        if block["rows"] < 15 or block["positives"] < 5 or block["negatives"] < 5:
            reasons.append("The %s fold does not have 15 rows, 5 positives, and 5 negatives." % label)
        if block["pr_auc"] <= block["base_pr_auc"]:
            reasons.append("The %s precision-recall score did not beat the base rate." % label)
        if block.get("roc_auc") is None or block["roc_auc"] <= 0.5:
            reasons.append("The %s ROC-AUC did not beat 0.5." % label)
        if block.get("brier") is None or block.get("base_brier") is None or block["brier"] >= block["base_brier"]:
            reasons.append("The %s Brier score did not beat the training base rate." % label)
    return {"supply": not reasons, "reasons": reasons}


def probability_for_valuation(experiment, scored):
    """The 30-day probability, or None when the experiment was not accepted."""
    if not experiment or not experiment.get("supply_to_valuation"):
        return None
    if not scored or not scored.get("coverage_sufficient"):
        return None
    probability = scored.get("probability")
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        return None
    probability = float(probability)
    if not 0.0 <= probability <= 1.0:
        return None
    return probability


def apply_probability(assumptions, probability):
    """Pass a caller-supplied probability into the existing scenario valuation.

    When the probability is missing, Black-Scholes is not called and no default
    is written onto the assumptions.
    """
    if isinstance(probability, bool) or not isinstance(probability, (int, float)):
        return {
            "probability": None,
            "valuation": None,
            "reason": "No reliable acquisition probability was available.",
        }
    probability = float(probability)
    if not 0.0 <= probability <= 1.0:
        return {
            "probability": None,
            "valuation": None,
            "reason": "The acquisition probability is outside 0 to 1.",
        }
    payload = dict(assumptions or {})
    payload["acquisition_probability"] = probability
    return {
        "probability": probability,
        "valuation": black_scholes.acquisition_option_value(payload),
        "reason": None,
    }
