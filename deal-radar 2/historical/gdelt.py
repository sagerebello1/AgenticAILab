"""GDELT DOC 2.0 news features. This module does not download data and does not fit a model."""
import re
from datetime import date, datetime, timedelta, timezone


DOC_COVERAGE_START = date(2017, 1, 1)
GKG_FILE_START = date(2015, 2, 19)

_SUFFIXES = {
    "inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited",
    "llc", "plc", "lp", "llp", "nv", "sa", "ag", "holdings", "holding", "group",
    "bancorp", "the", "new", "com", "cl", "de",
}
_AMBIGUOUS = {
    "bank", "first", "national", "american", "financial", "capital", "energy",
    "health", "global", "united", "general", "international", "industries",
    "systems", "services", "partners", "holdings", "group", "acquisition",
}
_TICKER_STOP = {
    "ALL", "BIG", "LOW", "KEY", "MAN", "SUN", "AIR", "CAR", "GAS", "OIL", "FUND",
    "BANK", "TECH", "DATA", "GOLD", "HOME", "FOOD", "LIFE", "REAL", "WEST", "EAST",
    "MAIN", "PLUS", "GROW", "OPEN", "PLAY", "SAFE", "TIME", "VIEW", "WELL", "WORK",
    "LOVE", "FIVE", "FOUR", "ONE", "NEW", "INC", "THE", "FOR", "AND",
}
_KEYWORD_CLAUSE = (
    '("strategic review" OR "strategic alternatives" OR "potential sale" OR '
    '"activist investor" OR "takeover interest" OR "merger rumor" OR "merger rumours" OR '
    "acquisition OR merger OR takeover)"
)


def clean_name(name):
    text = (name or "").replace(".", " ")
    text = re.sub(r"/[^/]+/", " ", text)
    text = re.sub(r"[^A-Za-z0-9 &-]", " ", text)
    tokens = [token for token in text.split() if token]
    while tokens and tokens[-1].lower() in _SUFFIXES:
        tokens.pop()
    while tokens and tokens[0].lower() == "the":
        tokens.pop(0)
    return " ".join(tokens)


def _ticker_term(ticker):
    token = (ticker or "").strip().upper()
    if len(token) < 3 or not token.isalpha() or token in _TICKER_STOP:
        return None
    return token


def identity(name, ticker):
    """A GDELT query, or a reason the company was not queried.

    A short ticker is never searched by itself. An unqueried company stays missing,
    which is not the same as a day with zero articles.
    """
    phrase = clean_name(name)
    tokens = phrase.split()
    ticker_term = _ticker_term(ticker)
    if not tokens:
        return {"status": "missing_name", "phrase": None, "ticker_term": ticker_term,
                "reason": "No company name remained after cleaning."}
    if len(tokens) == 1 and (len(tokens[0]) < 5 or tokens[0].lower() in _AMBIGUOUS):
        return {"status": "ambiguous", "phrase": phrase, "ticker_term": ticker_term,
                "reason": "The cleaned name is too short or too generic to search."}
    return {"status": "queryable", "phrase": phrase, "ticker_term": ticker_term, "reason": None}


def mention_query(phrase, ticker_term):
    parts = ['"%s"' % phrase]
    if ticker_term:
        parts.append('"%s"' % ticker_term)
    name = parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    return name + " sourcelang:english"


def keyword_query(phrase, ticker_term):
    name = mention_query(phrase, ticker_term).replace(" sourcelang:english", "")
    return name + " " + _KEYWORD_CLAUSE + " sourcelang:english"


def parse_gdelt_time(value):
    text = (value or "").strip().replace("Z", "").replace("-", "").replace(":", "")
    if "T" in text:
        text = text.replace("T", "")
    if len(text) < 8 or not text[:8].isdigit():
        raise ValueError("GDELT time is not a timestamp: %r" % (value,))
    day = date(int(text[0:4]), int(text[4:6]), int(text[6:8]))
    clock = text[8:14] if len(text) >= 14 and text[8:14].isdigit() else "000000"
    stamp = datetime(day.year, day.month, day.day, int(clock[0:2]), int(clock[2:4]), int(clock[4:6]),
                     tzinfo=timezone.utc)
    return day, stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_timeline(payload):
    """Daily buckets from a DOC timeline JSON object. Values are copied, not filled in."""
    if not isinstance(payload, dict) or not payload.get("timeline"):
        raise ValueError("GDELT did not return a timeline.")
    data = payload["timeline"][0].get("data") or []
    points = []
    for item in data:
        if "date" not in item or "value" not in item:
            raise ValueError("A GDELT timeline point is missing its date or value.")
        day, stamp = parse_gdelt_time(item["date"])
        points.append({
            "bucket_date": day,
            "bucket_at": stamp,
            "value": float(item["value"]),
            "norm": None if item.get("norm") is None else float(item["norm"]),
        })
    return points


def parse_articles(payload):
    """Article rows. seendate is when GDELT observed the article.

    The DOC article list does not provide a separate publisher timestamp. That field
    stays empty unless the payload itself has one.
    """
    if not isinstance(payload, dict):
        raise ValueError("GDELT article list is not an object.")
    rows = []
    for item in payload.get("articles") or []:
        seen = item.get("seendate")
        if not seen:
            raise ValueError("A GDELT article has no observation time.")
        day, stamp = parse_gdelt_time(seen)
        published = None
        for key in ("published", "publisheddate", "publicationdate", "datetime"):
            if item.get(key) and item.get(key) != seen:
                _, published = parse_gdelt_time(item[key])
                break
        rows.append({
            "url": item.get("url"),
            "title": item.get("title"),
            "seen_date": day,
            "seen_at": stamp,
            "published_at": published,
            "domain": item.get("domain"),
            "language": item.get("language"),
        })
    return rows


def on_or_before(points, snapshot):
    return [point for point in points if point["bucket_date"] <= snapshot]


def articles_on_or_before(rows, snapshot):
    return [row for row in rows if row["seen_date"] <= snapshot]


def _daily(points, average):
    """Collapse buckets to days. An hourly day counts only when all 24 hours were returned."""
    grouped = {}
    for point in points:
        grouped.setdefault(point["bucket_date"], []).append(point)
    hourly = any(len(items) > 1 for items in grouped.values())
    collapsed = {}
    for day, items in grouped.items():
        if not hourly:
            if len(items) == 1:
                collapsed[day] = items[0]["value"]
            continue
        by_hour = {}
        for point in items:
            stamp = point.get("bucket_at") or ""
            hour = int(stamp[11:13]) if len(stamp) >= 13 and stamp[11:13].isdigit() else None
            if hour is None or not 0 <= hour <= 23:
                continue
            by_hour.setdefault(hour, []).append(point["value"])
        if set(by_hour) != set(range(24)):
            continue
        hours = []
        for hour in range(24):
            values = by_hour[hour]
            hours.append(sum(values) / len(values) if average else sum(values))
        collapsed[day] = sum(hours) / 24 if average else sum(hours)
    return collapsed


def _complete_sum(values, start, end):
    if start > end:
        return None
    total = 0.0
    day = start
    while day <= end:
        if day not in values:
            return None
        total += values[day]
        day += timedelta(days=1)
    return total


def _tone_mean(values, start, end):
    """Average tone on days that have one. A day with no tone is not a zero."""
    if start > end:
        return None
    found = []
    day = start
    while day <= end:
        if day in values:
            found.append(values[day])
        day += timedelta(days=1)
    if not found:
        return None
    return sum(found) / len(found)


def feature_row(mentions, tone, keywords, snapshot):
    """Features known on snapshot. A missing day stays missing. An explicit zero stays zero.

    Change is the recent window minus the window of the same length immediately before it.
    Either window being incomplete makes the change missing.
    """
    mention_days = _daily(on_or_before(mentions, snapshot), average=False)
    keyword_days = _daily(on_or_before(keywords, snapshot), average=False)
    tone_days = _daily(on_or_before(tone, snapshot), average=True)

    def level(days, width):
        return _complete_sum(days, snapshot - timedelta(days=width - 1), snapshot)

    def change(days, width):
        recent_start = snapshot - timedelta(days=width - 1)
        prior_end = recent_start - timedelta(days=1)
        prior_start = prior_end - timedelta(days=width - 1)
        recent = _complete_sum(days, recent_start, snapshot)
        prior = _complete_sum(days, prior_start, prior_end)
        if recent is None or prior is None:
            return None
        return recent - prior

    mentions_30 = level(mention_days, 30)
    return {
        "mentions_7": level(mention_days, 7),
        "mentions_30": mentions_30,
        "mentions_90": level(mention_days, 90),
        "change_7": change(mention_days, 7),
        "change_30": change(mention_days, 30),
        "change_90": change(mention_days, 90),
        "tone_7": _tone_mean(tone_days, snapshot - timedelta(days=6), snapshot),
        "tone_30": _tone_mean(tone_days, snapshot - timedelta(days=29), snapshot),
        "tone_90": _tone_mean(tone_days, snapshot - timedelta(days=89), snapshot),
        "keywords_7": level(keyword_days, 7),
        "keywords_30": level(keyword_days, 30),
        "keywords_90": level(keyword_days, 90),
        "keyword_change_30": change(keyword_days, 30),
        "mentions_observed": mentions_30 is not None,
    }


def average_precision(labels, scores):
    positives = sum(labels)
    if not labels or positives == 0:
        return None
    order = sorted(range(len(labels)), key=lambda index: (scores[index], -index), reverse=True)
    hits = 0
    total = 0.0
    for rank, index in enumerate(order, start=1):
        if labels[index]:
            hits += 1
            total += hits / rank
    return total / positives


def brier(labels, scores):
    if not labels:
        return None
    return sum((score - label) ** 2 for score, label in zip(scores, labels)) / len(labels)


def classification(labels, scores, threshold):
    tp = fp = fn = 0
    for label, score in zip(labels, scores):
        predicted = score >= threshold
        if predicted and label:
            tp += 1
        elif predicted:
            fp += 1
        elif label:
            fn += 1
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"threshold": threshold, "precision": precision, "recall": recall,
            "true_positives": tp, "false_positives": fp, "false_negatives": fn}


def calibration(labels, scores, bins=5):
    if len(labels) < bins:
        return []
    order = sorted(zip(scores, labels))
    size = len(order) // bins
    if size == 0:
        return []
    rows = []
    for index in range(bins):
        chunk = order[index * size:(index + 1) * size if index < bins - 1 else len(order)]
        if not chunk:
            continue
        rows.append({
            "n": len(chunk),
            "mean_predicted": sum(score for score, _ in chunk) / len(chunk),
            "observed_rate": sum(label for _, label in chunk) / len(chunk),
        })
    return rows
