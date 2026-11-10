"""Labels for a market-wide acquisition screen.

A positive is a verified announcement inside the horizon. A negative exists only
when the observation window has closed and the announcement record for that
window is complete. A missing filing match is not a negative.
"""
from datetime import timedelta

from predictive.point_in_time import as_date


def quarter_ends(first_year, today):
    dates = []
    for year in range(first_year, today.year + 1):
        for month, day in ((3, 31), (6, 30), (9, 30), (12, 31)):
            candidate = as_date("%04d-%02d-%02d" % (year, month, day))
            if candidate <= today:
                dates.append(candidate)
    return dates


def label_window(announcements, snapshot, horizon_days, today, record_complete):
    """Return (label, reason). Label is 1, 0, or None.

    `announcements` are verified definitive announcement dates for one company.
    `record_complete` means every qualifying announcement in the window is known.
    This project does not have that record, so callers pass False and get None
    instead of a negative.
    """
    snapshot = as_date(snapshot)
    today = as_date(today)
    if snapshot is None or today is None or horizon_days <= 0:
        return None, "undated"
    if snapshot + timedelta(days=horizon_days) > today:
        return None, "censored"
    horizon_end = snapshot + timedelta(days=horizon_days)
    for announced in announcements or []:
        announced = as_date(announced)
        if announced is not None and snapshot < announced <= horizon_end:
            return 1, "verified announcement"
    if not record_complete:
        return None, "announcement record is incomplete"
    return 0, "complete window and no verified announcement"
