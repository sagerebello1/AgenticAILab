"""Point-in-time labels. A horizon that has not finished is left blank, not marked zero."""
from datetime import timedelta


def horizon_label(snapshot, announcement, horizon_days, today):
    """1 if the announcement falls inside the horizon, 0 if it does not, None if censored."""
    if snapshot is None or today is None:
        return None
    if snapshot + timedelta(days=horizon_days) > today:
        return None
    if announcement is None:
        return 0
    delta = (announcement - snapshot).days
    if delta <= 0:
        return None
    return 1 if delta <= horizon_days else 0


def label_set(snapshot, announcement, today):
    return {days: horizon_label(snapshot, announcement, days, today) for days in (30, 90, 180)}


def control_label(snapshot, hit_dates, horizon_days, today):
    """0 only when every stored hit is outside the horizon and the horizon has ended.

    hit_dates are filing dates of an unverified phrase match. Those are not positives.
    """
    if snapshot is None or snapshot + timedelta(days=horizon_days) > today:
        return None
    for day in hit_dates or []:
        delta = (day - snapshot).days
        if 0 < delta <= horizon_days:
            return None
    return 0
