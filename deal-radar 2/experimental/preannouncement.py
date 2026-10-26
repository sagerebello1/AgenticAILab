"""Experimental score for a question the production app does not answer.

Question: will this company become the target of a publicly announced definitive
acquisition agreement or tender offer within the next 30 calendar days?

The score is the stock's return over the prior 21 trading sessions minus the
S&P 500 tracker's return over the same sessions. It was written down before
any case was scored. It is not fit to outcomes, and it is not a probability.

Announcement-filing flags are not inputs. quote.close_probability is not called.
"""


def bars_before(series, prediction_date):
    """Price bars whose session date is strictly before the prediction date."""
    return [(day, close) for day, close in series if day < prediction_date]


def _return(bars, sessions):
    """Return across `sessions` trading steps, using the last bar as the end."""
    if len(bars) < sessions + 1:
        raise ValueError("Need %d closes before the prediction date." % (sessions + 1))
    start = bars[-(sessions + 1)][1]
    end = bars[-1][1]
    if start <= 0 or end <= 0:
        raise ValueError("A non-positive close cannot be turned into a return.")
    return end / start - 1.0


def _spy_on(spy_bars, day):
    """Latest SPY close on or before `day`. The caller has already cut the series."""
    chosen = None
    for bar_day, close in spy_bars:
        if bar_day <= day:
            chosen = (bar_day, close)
        else:
            break
    return chosen


def price_features(stock_bars, spy_bars):
    """Features from closes that are already limited to dates before the cutoff.

    stock_bars and spy_bars are lists of (date, close), oldest first.
    """
    if len(stock_bars) < 22:
        raise ValueError("Need 22 closes before the prediction date.")
    start_day = stock_bars[-22][0]
    end_day = stock_bars[-1][0]
    spy_start = _spy_on(spy_bars, start_day)
    spy_end = _spy_on(spy_bars, end_day)
    if spy_start is None or spy_end is None:
        raise ValueError("SPY has no close on or before the stock's window.")
    if (start_day - spy_start[0]).days > 5 or (end_day - spy_end[0]).days > 5:
        raise ValueError("SPY dates do not line up with the stock dates.")
    if spy_start[1] <= 0 or spy_end[1] <= 0:
        raise ValueError("A non-positive SPY close cannot be turned into a return.")
    ret_21 = _return(stock_bars, 21)
    ret_5 = _return(stock_bars, 5)
    spy_ret_21 = spy_end[1] / spy_start[1] - 1.0
    return {
        "last_price_date": end_day.isoformat(),
        "first_price_date": start_day.isoformat(),
        "n_bars": len(stock_bars),
        "ret_21": ret_21,
        "ret_5": ret_5,
        "spy_ret_21": spy_ret_21,
        "spy_start_date": spy_start[0].isoformat(),
        "spy_end_date": spy_end[0].isoformat(),
        "abnormal_21": ret_21 - spy_ret_21,
    }


def ranking_score(features):
    """Experimental ranking score. Larger means a stronger 21-session run-up.

    This is not a probability and it is not calibrated.
    """
    if "abnormal_21" not in features:
        raise ValueError("The score only accepts a pre-announcement return feature.")
    return float(features["abnormal_21"])
