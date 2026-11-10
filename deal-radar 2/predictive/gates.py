"""Minimum samples required before a probability model may be saved.

Below these counts the pipeline records the rows and does not fit a model.
"""

# Company-dates with features known before the announcement.
ACQUISITION = {"rows": 100, "positives": 20, "negatives": 20, "holdout": 15}

# Deals with a pre-announcement close and a post-announcement close.
PRICE = {"deals": 40}

# Announced deals with a later close or termination label.
CLOSING = {"deals": 40, "terminations": 8}


def _need(have, minimum):
    return [name for name, floor in minimum.items() if have.get(name, 0) < floor]


def acquisition_ready(counts):
    missing = _need(counts, ACQUISITION)
    return not missing, missing


def price_ready(counts):
    missing = _need(counts, PRICE)
    return not missing, missing


def closing_ready(counts):
    missing = _need(counts, CLOSING)
    return not missing, missing
