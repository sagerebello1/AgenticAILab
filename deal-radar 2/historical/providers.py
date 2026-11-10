"""Optional price providers. A missing key raises and does not invent a bar."""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone


class SourceError(Exception):
    pass


def _key(name):
    return os.environ.get(name, "").strip()


def _read_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "DealRadar historical research"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())


def financial_modeling_prep_bars(symbol, start, end):
    key = _key("FMP_API_KEY")
    if not key:
        raise SourceError("FMP_API_KEY is not set. Financial Modeling Prep was not called.")
    params = urllib.parse.urlencode({"from": start.isoformat(), "to": end.isoformat(), "apikey": key})
    url = "https://financialmodelingprep.com/api/v3/historical-price-full/%s?%s" % (
        urllib.parse.quote(symbol), params)
    payload = _read_json(url)
    rows = payload.get("historical") if isinstance(payload, dict) else None
    if not rows:
        return []
    bars = []
    for row in rows:
        if row.get("date") and row.get("close") is not None:
            bars.append({
                "date": row["date"],
                "close": float(row["close"]),
                "adjClose": None if row.get("adjClose") is None else float(row["adjClose"]),
                "volume": None if row.get("volume") is None else float(row["volume"]),
            })
    return bars


def polygon_bars(symbol, start, end):
    key = _key("POLYGON_API_KEY")
    if not key:
        raise SourceError("POLYGON_API_KEY is not set. Polygon was not called.")
    params = urllib.parse.urlencode({"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key})
    url = "https://api.polygon.io/v2/aggs/ticker/%s/range/1/day/%s/%s?%s" % (
        urllib.parse.quote(symbol), start.isoformat(), end.isoformat(), params)
    payload = _read_json(url)
    bars = []
    for row in payload.get("results") or []:
        if row.get("t") is None or row.get("c") is None:
            continue
        day = datetime.fromtimestamp(row["t"] / 1000, tz=timezone.utc).date()
        bars.append({
            "date": day,
            "close": float(row["c"]),
            "adjClose": float(row["c"]),
            "volume": None if row.get("v") is None else float(row["v"]),
        })
    return bars


def stooq_status(body):
    """Stooq is usable only when the body is CSV. An interstitial page is not a price."""
    text = body or ""
    if text.startswith("Date,") or text.startswith("\ufeffDate,"):
        return "csv"
    if "requires JavaScript" in text or "<html" in text.lower():
        return "blocked"
    return "unreadable"
