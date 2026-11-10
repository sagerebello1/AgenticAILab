"""Yahoo chart bars, rejected when the symbol's current listing starts too late.

A missing bar stays missing. Polygon and Financial Modeling Prep are separate adapters.
"""
import json
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from historical.providers import SourceError, financial_modeling_prep_bars, polygon_bars

CHART = "https://%s.finance.yahoo.com/v8/finance/chart/%s?%s"
UA = "Mozilla/5.0 (compatible; DealRadar research prototype)"


def _ssl_context():
    ca = "/etc/ssl/cert.pem"
    if os.path.exists(ca):
        try:
            return ssl.create_default_context(cafile=ca)
        except ssl.SSLError:
            pass
    return ssl.create_default_context()


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b""
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise SourceError("Yahoo chart request failed: %s" % exc)


def _day(stamp):
    return datetime.fromtimestamp(int(stamp), tz=timezone.utc).date()


def parse_chart(payload):
    """Bars from a Yahoo chart body. An error payload has no bars."""
    try:
        data = json.loads(payload)
    except (TypeError, json.JSONDecodeError):
        return {"bars": [], "meta": {}, "error": "Yahoo chart was not JSON"}
    chart = data.get("chart") or {}
    error = chart.get("error") or {}
    result = (chart.get("result") or [None])[0] or {}
    meta = result.get("meta") or {}
    stamps = result.get("timestamp") or []
    quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    adjusted = (((result.get("indicators") or {}).get("adjclose") or [{}])[0]).get("adjclose") or []
    bars = []
    for index, stamp in enumerate(stamps):
        close = closes[index] if index < len(closes) else None
        if close is None:
            continue
        bars.append({
            "date": _day(stamp),
            "close": float(close),
            "adjClose": None if index >= len(adjusted) or adjusted[index] is None else float(adjusted[index]),
            "volume": None if index >= len(volumes) or volumes[index] is None else float(volumes[index]),
        })
    return {
        "bars": bars,
        "meta": meta,
        "error": error.get("description"),
        "errorCode": error.get("code"),
    }


def listing_decision(meta, historical_date, requested_symbol):
    """Whether these bars belong to the company that had this symbol on the historical date."""
    yahoo_symbol = (meta.get("symbol") or "").upper()
    requested = (requested_symbol or "").upper()
    if yahoo_symbol and requested and yahoo_symbol.replace(".", "-") != requested.replace(".", "-"):
        return "symbol_mismatch"
    first = meta.get("firstTradeDate")
    if first and historical_date is not None:
        first_day = _day(first)
        if first_day > historical_date:
            return "current_listing_starts_after_historical_date"
    return "ok"


def last_bar_on_or_before(bars, day):
    chosen = None
    for bar in bars or []:
        if bar["date"] <= day and (chosen is None or bar["date"] > chosen["date"]):
            chosen = bar
    return chosen


def trading_offset(bars, day, sessions):
    """sessions 0 is the first session on or after day. Negative sessions count backward."""
    ordered = sorted(bars or [], key=lambda bar: bar["date"])
    if sessions < 0:
        before = [bar for bar in ordered if bar["date"] < day]
        if len(before) < abs(sessions):
            return None
        return before[sessions]
    after = [bar for bar in ordered if bar["date"] >= day]
    if len(after) <= sessions:
        return None
    return after[sessions]


def calendar_gaps(bars, minimum_days=6):
    ordered = sorted(bars or [], key=lambda bar: bar["date"])
    gaps = []
    for left, right in zip(ordered, ordered[1:]):
        span = (right["date"] - left["date"]).days
        if span > minimum_days:
            gaps.append({
                "after": left["date"].isoformat(),
                "before": right["date"].isoformat(),
                "calendarDays": span,
            })
    return gaps


def fetch_yahoo(symbol, start, end):
    """One chart request. HTTP errors are returned, not replaced with a price."""
    query = urllib.parse.urlencode({
        "period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
        "period2": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400,
        "interval": "1d",
        "events": "div,splits",
        "includeAdjustedClose": "true",
    })
    url = CHART % ("query1", urllib.parse.quote(symbol), query)
    status, body = _get(url)
    parsed = parse_chart(body)
    parsed["httpStatus"] = status
    parsed["source"] = "yahoo-chart"
    parsed["requestedSymbol"] = symbol
    return parsed


def fetch_yahoo_meta(symbol):
    """Current listing identity. Recent bars from this call are not historical prices."""
    query = urllib.parse.urlencode({"range": "5d", "interval": "1d"})
    url = CHART % ("query1", urllib.parse.quote(symbol), query)
    status, body = _get(url)
    parsed = parse_chart(body)
    parsed["httpStatus"] = status
    parsed["bars"] = []
    return parsed


def other_providers(symbol, start, end):
    """Call paid providers only when a key is set. Each miss is an error string and no bars."""
    notes = []
    bars = []
    for name, func in (("financial-modeling-prep", financial_modeling_prep_bars), ("polygon", polygon_bars)):
        try:
            found = func(symbol, start, end)
            for bar in found:
                bar["source"] = name
                bars.append(bar)
        except SourceError as exc:
            notes.append(str(exc))
    return bars, notes
