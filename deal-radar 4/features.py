"""Turns an announcement filing into the numbers the close-probability model is trained on.

The same function is used when training (on historical filings) and when scoring a new deal, so
the model never sees a feature at scoring time that it did not see in training. Only facts that
are in the announcement filing are used. Nothing that happens later (price moves, news, the
outcome itself) can leak in.
"""
import math
import re

import terms

SIC_DIVISIONS = [("agri", 1, 9), ("mining", 10, 14), ("construction", 15, 17), ("manufacturing", 20, 39),
                 ("transport_utilities", 40, 49), ("wholesale", 50, 51), ("retail", 52, 59),
                 ("finance", 60, 67), ("services", 70, 89), ("public_admin", 91, 99)]

TEXT_RULES = [
    ("reverse_fee", r"reverse\s+termination\s+fee|parent\s+termination\s+fee"),
    ("spac", r"trust\s+account|special\s+purpose\s+acquisition|business\s+combination\s+agreement"),
    ("going_private", r"special\s+committee|affiliates\s+of|funds\s+(?:managed|advised)\s+by|private\s+equity|take[- ]private"),
    ("voting_agreement", r"voting\s+agreements?|support\s+agreements?|tender\s+and\s+support"),
    ("appraisal", r"appraisal\s+rights|dissenters"),
    ("majority_of_minority", r"majority\s+of\s+the\s+minority|unaffiliated\s+(?:stockholders|shareholders)"),
    ("debt_commitment", r"debt\s+commitment\s+letter|financing\s+commitment|commitment\s+letters?"),
    ("unsolicited", r"unsolicited|hostile|proxy\s+contest"),
    ("outside_date", r"outside\s+date|end\s+date|termination\s+date"),
]
COMPILED = [(n, re.compile(rx, re.I)) for n, rx in TEXT_RULES]

NUMERIC = ["cash", "stock", "mixed", "hsr", "second_request", "n_foreign", "n_other", "fin_cond", "no_fin_cond",
           "tender", "vote", "go_shop", "term_fee"] + [n for n, _ in TEXT_RULES] + ["log_len"]
FEATURES = NUMERIC + ["sic_" + n for n, _, _ in SIC_DIVISIONS]

LABELS = {
    "cash": "Paid in cash", "stock": "Paid in acquirer stock", "mixed": "Paid in cash and stock",
    "hsr": "US antitrust review (HSR)", "second_request": "Second request from regulators",
    "n_foreign": "Foreign regulator approvals", "n_other": "Sector regulator approvals",
    "fin_cond": "Closing depends on financing", "no_fin_cond": "No financing condition",
    "tender": "Tender offer", "vote": "Shareholder vote required", "go_shop": "Go-shop period",
    "term_fee": "Break fee in the agreement", "reverse_fee": "Reverse break fee (buyer pays if it fails)",
    "spac": "Blank-check (SPAC) merger", "going_private": "Buyout by a fund or insiders",
    "voting_agreement": "Holders already signed support agreements", "appraisal": "Appraisal rights",
    "majority_of_minority": "Needs a vote of unaffiliated holders", "debt_commitment": "Debt financing commitment",
    "unsolicited": "Unsolicited or contested", "outside_date": "Outside date stated", "log_len": "Length of the filing",
}
for _n, _a, _b in SIC_DIVISIONS:
    LABELS["sic_" + _n] = "Industry: " + _n.replace("_", " ")


def sic_division(sic):
    try:
        major = int(str(sic).zfill(4)[:2])
    except (TypeError, ValueError):
        return None
    for name, a, b in SIC_DIVISIONS:
        if a <= major <= b:
            return name
    return None


def vectorize(text, sic=None):
    """Return {feature name: number} for one announcement filing."""
    t = terms.extract_terms(text)
    f = t["flags"]
    row = dict.fromkeys(FEATURES, 0.0)
    cons = t["consideration"]
    row["cash"], row["stock"], row["mixed"] = float(cons == "cash"), float(cons == "stock"), float(cons == "mixed")
    row["hsr"] = float(bool(f.get("hsr")))
    row["second_request"] = float(bool(f.get("secondRequest")))
    row["n_foreign"] = float(len(f.get("foreign") or []))
    row["n_other"] = float(len(f.get("other") or []))
    row["fin_cond"] = float(f.get("financingCondition") is True)
    row["no_fin_cond"] = float(f.get("financingCondition") is False)
    row["tender"], row["vote"], row["go_shop"] = float(bool(f.get("tender"))), float(bool(f.get("vote"))), float(bool(f.get("goShop")))
    row["term_fee"] = float(bool(f.get("termFees")))
    for name, rx in COMPILED:
        row[name] = float(bool(rx.search(text)))
    row["log_len"] = math.log10(max(len(text), 1))
    div = sic_division(sic)
    if div:
        row["sic_" + div] = 1.0
    return row, t


def filer_is_target(filer, terms_out):
    """Guess whether the filing company is the target (True), the buyer (False) or unclear (None)."""
    if not filer:
        return None
    first = filer.lower().split()[0]
    parent, company = terms_out.get("parent"), terms_out.get("company")
    if parent and parent.lower().split()[0] == first:
        return False
    if company and company.lower().split()[0] == first:
        return True
    return None
