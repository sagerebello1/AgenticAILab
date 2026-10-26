"""Stock prices from Yahoo Finance's daily chart: the latest close and the close before the
announcement.

Prices come from Yahoo's chart endpoint (query1.finance.yahoo.com), which is unofficial and may
change or rate-limit. A daily bar is delayed. It is not a real-time quote. Option chains are not
retrieved: Yahoo's options endpoint returned HTTP 401, and that check is not bypassed.

What each number means for the model
  spot       latest daily close. Delayed, not a real-time quote.
  downside   last close BEFORE the announcement date. This is the "deal breaks" price. If the news
             leaked early this is too high, so check it against the chart.
  vol        annualised volatility of daily returns over the 60 trading days before the announcement,
             a stand-in for how the stock behaved before it became a takeover target. Do not use the
             option's implied volatility here, because for a deal target it is already squashed by the deal.
"""
import json
import math
import os
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?%s"
UA = "Mozilla/5.0 (compatible; DealRadar research prototype)"


class MarketError(Exception):
    pass


def _ssl_context():
    """Use the system certificate bundle when this Python has none of its own.

    The python.org macOS installer often cannot verify HTTPS until its
    certificates are installed. /etc/ssl/cert.pem is the system bundle and
    needs no extra package.
    """
    ca = "/etc/ssl/cert.pem"
    if os.path.exists(ca):
        try:
            return ssl.create_default_context(cafile=ca)
        except ssl.SSLError:
            pass
    return ssl.create_default_context()


def _fetch_chart(ticker, query, timeout=15):
    """One Yahoo chart response. A failure names the chart and does not invent a price."""
    req = urllib.request.Request(CHART % (urllib.parse.quote(ticker), query), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as r:
            data = json.loads(r.read())
    except json.JSONDecodeError:
        raise MarketError("Yahoo chart for %s did not return price data. No price was substituted." % ticker)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise MarketError("Yahoo chart rate-limited the request for %s. No price was substituted." % ticker)
        raise MarketError("Yahoo chart for %s returned HTTP %d. No price was substituted." % (ticker, e.code))
    except (TimeoutError, socket.timeout):
        raise MarketError("Yahoo chart for %s timed out after %d seconds. No price was substituted." % (ticker, timeout))
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
            raise MarketError("Yahoo chart for %s timed out after %d seconds. No price was substituted." % (ticker, timeout))
        raise MarketError("Yahoo chart for %s did not answer. No price was substituted. %s" % (ticker, reason))
    res = (data.get("chart", {}).get("result") or [None])[0]
    if not res:
        raise MarketError("Yahoo has no listing for %s. No price was substituted." % ticker)
    return res


def history(ticker, start, end, timeout=15):
    """Daily closes as a list of (date, close), oldest first."""
    q = urllib.parse.urlencode({"period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
                                "period2": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400,
                                "interval": "1d", "events": "div,splits"})
    res = _fetch_chart(ticker, q, timeout)
    if not res.get("timestamp"):
        raise MarketError("Yahoo has no price history for %s" % ticker)
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(res["timestamp"], closes):
        if c is not None:
            out.append((datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(c)))
    return out


def price_move(latest, previous):
    """Point and percent change from the prior close.

    None means the change is missing. A real zero is returned as unchanged,
    not as a missing value.
    """
    try:
        latest = float(latest)
        previous = float(previous)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latest) or not math.isfinite(previous):
        return None
    change = latest - previous
    if abs(change) < 1e-8:
        direction = "unchanged"
        change = 0.0
    elif change > 0:
        direction = "up"
    else:
        direction = "down"
    pct = 0.0 if change == 0 else (None if previous == 0 else change / previous)
    return {"change": change, "changePct": pct, "direction": direction}


def identity(ticker, timeout=12):
    """Symbol and company name from the chart listing. The name is omitted when the chart has none."""
    query = urllib.parse.urlencode({"range": "5d", "interval": "1d"})
    res = _fetch_chart(ticker, query, timeout)
    meta = res.get("meta") or {}
    symbol = (meta.get("symbol") or "").strip()
    long_name = (meta.get("longName") or "").strip()
    short_name = (meta.get("shortName") or "").strip()
    if not symbol:
        raise MarketError("Yahoo has no listing for %s. No company name was substituted." % ticker)
    return {
        "symbol": symbol,
        "name": long_name or short_name or None,
        "instrument": (meta.get("instrumentType") or "").strip().upper() or None,
        "source": "yahoo-chart",
    }


def index_quote(symbol, today=None, timeout=12):
    """Latest daily close and the change from the previous daily close.

    The bar is delayed. This does not label it real-time.
    """
    today = today or date.today()
    series = history(symbol, today - timedelta(days=14), today + timedelta(days=1), timeout=timeout)
    last_day, last_px = series[-1]
    previous = series[-2][1] if len(series) > 1 else None
    moved = price_move(last_px, previous)
    return {
        "querySymbol": symbol,
        "price": last_px,
        "previous": previous,
        "asOf": last_day.isoformat(),
        "change": None if moved is None else moved["change"],
        "changePct": None if moved is None else moved["changePct"],
        "direction": None if moved is None else moved["direction"],
    }


def stats(series, filed_on):
    """From a price series work out spot, the pre-announcement close and pre-announcement volatility."""
    if not series:
        raise MarketError("No prices")
    spot = series[-1][1]
    before = [(d, c) for d, c in series if d < filed_on]
    down = vol = None
    if before:
        down = before[-1][1]
        tail = [c for _, c in before[-61:]]
        if len(tail) >= 20:
            rets = [math.log(b / a) for a, b in zip(tail, tail[1:]) if a > 0 and b > 0]
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            vol = math.sqrt(var * 252)
    return {"spot": spot, "downside": down, "vol": vol, "asOf": series[-1][0].isoformat()}


def contract(ticker, kind, strike, days):
    """Options chains are not retrieved.

    Yahoo's options endpoint answered HTTP 401 on 19 October 2026. Working around
    that session check would bypass an access restriction, so no premium is returned.
    """
    return None, ("No free options chain is available for %s. Yahoo's options endpoint "
                  "returned HTTP 401. Type the bid and ask yourself. A premium will not be filled in." % ticker)


def snapshot(ticker, filed_on, kind="call", strike=None, days=60):
    start = (filed_on or date.today()) - timedelta(days=130)
    series = history(ticker, start, date.today())
    out = stats(series, filed_on or date.today())
    out["ticker"] = ticker
    out["option"], out["optionNote"] = (contract(ticker, kind, strike, days) if strike else (None, "Enter a strike to look up an option."))
    return out
