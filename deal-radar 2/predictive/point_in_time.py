"""Features and labels known on a historical prediction date.

Nothing in the feature vector is taken from the announcement, the offer, or the
label. A missing input stays missing. A bar, filing, or news row dated after
the prediction date is ignored.
"""
import math
from datetime import date, timedelta

from historical.labels import horizon_label

VALUE_COLUMNS = (
    "return_7", "return_30", "return_90",
    "abnormal_7", "abnormal_30", "abnormal_90",
    "volume_change_7", "volume_change_30",
    "volatility_30", "log_market_cap",
    "log_assets", "revenue_to_assets", "cash_to_assets", "debt_to_assets",
    "equity_to_assets", "book_to_market", "days_since_10k",
    "news_mentions", "news_sources", "news_tone", "news_acquisition_mentions",
)
HORIZONS = (30, 60, 90)


def as_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _first_after(bars, day):
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if bars[mid]["date"] <= day:
            lo = mid + 1
        else:
            hi = mid
    return lo


def last_index(bars, day):
    """Index of the last bar on or before day, or -1 when every bar is later."""
    return _first_after(bars, day) - 1


def _slice(bars, start_after, end):
    begin = _first_after(bars, start_after)
    stop = _first_after(bars, end)
    return bars[begin:stop]


def window_return(bars, snapshot, days):
    """Close-to-close return ending on the last bar known that day.

    The earlier close has to sit far enough back that a one-day quote is not
    reported as a 90-day return. Bars after `snapshot` are not read.
    """
    end_at = last_index(bars, snapshot)
    start_at = last_index(bars, snapshot - timedelta(days=days))
    if end_at < 0 or start_at < 0:
        return None
    end = bars[end_at]
    start = bars[start_at]
    if start["date"] >= end["date"]:
        return None
    if (end["date"] - start["date"]).days < int(days * 0.6):
        return None
    if start["close"] <= 0 or end["close"] <= 0:
        return None
    return end["close"] / start["close"] - 1.0


def volatility(bars, snapshot, sessions=30):
    """Standard deviation of the last `sessions` daily returns known that day."""
    end_at = last_index(bars, snapshot)
    if end_at < sessions:
        return None
    window = bars[end_at - sessions:end_at + 1]
    returns = []
    for earlier, later in zip(window, window[1:]):
        if earlier["close"] <= 0 or later["close"] <= 0:
            return None
        returns.append(later["close"] / earlier["close"] - 1.0)
    if len(returns) < sessions:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((item - mean) ** 2 for item in returns) / (len(returns) - 1)
    return math.sqrt(variance)


def volume_change(bars, snapshot, days, minimum):
    recent = _slice(bars, snapshot - timedelta(days=days), snapshot)
    prior = _slice(bars, snapshot - timedelta(days=2 * days), snapshot - timedelta(days=days))
    recent_volume = [bar["volume"] for bar in recent if bar.get("volume") is not None]
    prior_volume = [bar["volume"] for bar in prior if bar.get("volume") is not None]
    if len(recent_volume) < minimum or len(prior_volume) < minimum:
        return None
    prior_mean = sum(prior_volume) / len(prior_volume)
    if prior_mean <= 0:
        return None
    return (sum(recent_volume) / len(recent_volume)) / prior_mean - 1.0


def _known_number(value, filed, snapshot):
    """A financial figure is usable only when its filed date is on or before the snapshot."""
    if value is None:
        return None
    filed_on = as_date(filed)
    if filed_on is None or filed_on > snapshot:
        return None
    return float(value)


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def news_features(record, snapshot):
    """News counts for this prediction date only.

    A record from another date is not carried forward and is not treated as zero.
    An explicit zero from a completed observation stays zero.
    """
    blank = {
        "news_mentions": None,
        "news_sources": None,
        "news_tone": None,
        "news_acquisition_mentions": None,
        "news_observed": 0,
    }
    if not record:
        return blank
    observed_on = as_date(record.get("snapshot_date"))
    if observed_on != snapshot or record.get("reason") != "observed":
        return blank
    if record.get("mentions") is None:
        return blank
    return {
        "news_mentions": float(record["mentions"]),
        "news_sources": None if record.get("sources") is None else float(record["sources"]),
        "news_tone": None if record.get("tone") is None else float(record["tone"]),
        "news_acquisition_mentions": (
            None if record.get("acquisition_mentions") is None else float(record["acquisition_mentions"])
        ),
        "news_observed": 1,
    }


def labels_for(snapshot, announcement, kind, stored, today):
    """30, 60, and 90 day labels. A horizon that has not ended is None, not zero."""
    if kind == "target_pre":
        return {days: horizon_label(snapshot, announcement, days, today) for days in HORIZONS}
    labels = {30: stored.get(30), 90: stored.get(90), 60: None}
    if labels[90] == 0:
        labels[60] = 0
    elif labels[30] == 1:
        labels[60] = 1
    return labels


def feature_row(snapshot, price_bars, market_bars, news_record):
    """Point-in-time features. `snapshot` is a date. Price bars must be sorted."""
    end_at = last_index(price_bars or [], snapshot)
    price_known = end_at >= 0
    returns = {
        7: window_return(price_bars, snapshot, 7) if price_known else None,
        30: window_return(price_bars, snapshot, 30) if price_known else None,
        90: window_return(price_bars, snapshot, 90) if price_known else None,
    }
    market = {
        days: window_return(market_bars, snapshot, days) if market_bars else None
        for days in (7, 30, 90)
    }
    abnormal = {
        days: None if returns[days] is None or market[days] is None else returns[days] - market[days]
        for days in (7, 30, 90)
    }
    close = price_bars[end_at]["close"] if price_known else None
    features = {
        "return_7": returns[7],
        "return_30": returns[30],
        "return_90": returns[90],
        "abnormal_7": abnormal[7],
        "abnormal_30": abnormal[30],
        "abnormal_90": abnormal[90],
        "volume_change_7": volume_change(price_bars, snapshot, 7, 3) if price_known else None,
        "volume_change_30": volume_change(price_bars, snapshot, 30, 8) if price_known else None,
        "volatility_30": volatility(price_bars, snapshot) if price_known else None,
        "log_market_cap": None,
        "price_known": price_known,
        "close": close,
    }
    features.update(news_features(news_record, snapshot))
    return features


def statement_features(features, snapshot, statements):
    assets = _known_number(statements.get("assets"), statements.get("assets_filed"), snapshot)
    revenue = _known_number(statements.get("revenue"), statements.get("revenue_filed"), snapshot)
    cash = _known_number(statements.get("cash"), statements.get("cash_filed"), snapshot)
    equity = _known_number(statements.get("equity"), statements.get("equity_filed"), snapshot)
    debt = _known_number(statements.get("debt"), statements.get("debt_filed"), snapshot)
    shares = _known_number(statements.get("shares"), statements.get("shares_filed"), snapshot)
    features["log_assets"] = math.log(assets) if assets and assets > 0 else None
    features["revenue_to_assets"] = _ratio(revenue, assets)
    features["cash_to_assets"] = _ratio(cash, assets)
    features["debt_to_assets"] = _ratio(debt, assets)
    features["equity_to_assets"] = _ratio(equity, assets)
    market_cap = None
    features["log_market_cap"] = None
    if shares and shares > 0 and features.get("close") and features["close"] > 0:
        market_cap = shares * features["close"]
        features["log_market_cap"] = math.log(market_cap)
    features["book_to_market"] = None if market_cap is None or equity is None else equity / market_cap
    filed_10k = as_date(statements.get("latest_10k_date"))
    features["days_since_10k"] = None if filed_10k is None or filed_10k > snapshot else (snapshot - filed_10k).days
    return features


def coverage(features):
    groups = {
        "return_30": features.get("return_30") is not None,
        "return_90": features.get("return_90") is not None,
        "abnormal_30": features.get("abnormal_30") is not None,
        "volume_30": features.get("volume_change_30") is not None,
        "volatility": features.get("volatility_30") is not None,
        "market_cap": features.get("log_market_cap") is not None,
        "financials": features.get("log_assets") is not None,
        "news": features.get("news_observed") == 1,
    }
    present = sum(1 for ready in groups.values() if ready)
    return {
        "groups": groups,
        "fraction": present / float(len(groups)),
        "sufficient_for_valuation": groups["return_30"] and groups["volatility"],
    }


def examine(row, price_bars, market_bars, news_record, today, name=None):
    """One company-date. The result keeps the label beside the features for evaluation."""
    snapshot = as_date(row.get("snapshot_date"))
    announcement = as_date(row.get("announcement_date"))
    labels = labels_for(
        snapshot, announcement, row.get("kind"),
        {30: row.get("label_30"), 90: row.get("label_90"), 180: row.get("label_180")},
        today,
    )
    features = feature_row(snapshot, price_bars or [], market_bars or [], news_record)
    features = statement_features(features, snapshot, row)
    gap = None if announcement is None or snapshot is None else (announcement - snapshot).days
    return {
        "cik": row.get("cik"),
        "ticker": row.get("ticker") or None,
        "name": name,
        "snapshot_date": None if snapshot is None else snapshot.isoformat(),
        "announcement_date": None if announcement is None else announcement.isoformat(),
        "kind": row.get("kind"),
        "gap_days": gap,
        "labels": labels,
        "features": features,
        "coverage": coverage(features),
        "price_known": bool(features.get("price_known")),
    }


def column_plan(include_news):
    values = [name for name in VALUE_COLUMNS if include_news or not name.startswith("news_")]
    names = list(values) + ["miss_" + name for name in values]
    if include_news:
        names.append("news_observed")
    return names


def row_vector(features, names):
    """Missing values stay None so the training fold can impute them on its own."""
    vector = []
    for name in names:
        if name == "news_observed":
            vector.append(float(features.get("news_observed") or 0))
        elif name.startswith("miss_"):
            vector.append(0.0 if features.get(name[5:]) is not None else 1.0)
        else:
            value = features.get(name)
            vector.append(None if value is None else float(value))
    return vector


def group_date(rows):
    """When the company's outcome was known. Announcement dates sort acquired companies."""
    announcements = [row["announcement_date"] for row in rows if row.get("announcement_date")]
    if announcements:
        return max(announcements)
    return max(row["snapshot_date"] for row in rows)


def _row_time(row):
    return row.get("announcement_date") or row["snapshot_date"]


def chronological_split(rows, train_fraction=0.6, validation_fraction=0.2):
    """Later companies form the holdout. A company is never in two folds.

    An earlier deal for a holdout company is dropped. It is not used as a
    training row, and it is not scored as if the prediction date were in the
    later period.
    """
    grouped = {}
    for row in rows:
        if row.get("cik") is None:
            raise ValueError("A modeling row needs a CIK.")
        grouped.setdefault(row["cik"], []).append(row)
    ordered = sorted(grouped, key=lambda cik: (group_date(grouped[cik]), cik))
    count = len(ordered)
    if count < 3:
        raise ValueError("A chronological split needs at least three companies.")
    train_n = max(1, int(count * train_fraction))
    val_n = max(1, int(count * validation_fraction))
    if train_n + val_n >= count:
        val_n = 1
        train_n = count - 2
    bounds = {
        "train": ordered[:train_n],
        "validation": ordered[train_n:train_n + val_n],
        "test": ordered[train_n + val_n:],
    }
    val_start = group_date(grouped[bounds["validation"][0]])
    test_start = group_date(grouped[bounds["test"][0]])
    folds = {"train": [], "validation": [], "test": [], "excluded": []}
    assigned = {}
    for name, ciks in bounds.items():
        for cik in ciks:
            assigned[cik] = name
            company_time = group_date(grouped[cik])
            for row in grouped[cik]:
                row["group_date"] = company_time
                stamp = _row_time(row)
                keep = (
                    (name == "train" and stamp < val_start)
                    or (name == "validation" and val_start <= stamp < test_start)
                    or (name == "test" and stamp >= test_start)
                )
                row["fold"] = name if keep else "excluded"
                folds[row["fold"]].append(row)
    return {
        "folds": folds,
        "companies": {name: list(ciks) for name, ciks in bounds.items()},
        "assigned": assigned,
        "val_start": val_start,
        "test_start": test_start,
    }
