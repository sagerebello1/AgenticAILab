"""Live prices from Yahoo Finance: today's stock price, the undisturbed price from before the
announcement, normal volatility, and (optionally) a real option quote.

Prices come from Yahoo's chart endpoint (query1.finance.yahoo.com), which is unofficial and may
change or rate-limit. Option quotes need the optional `yfinance` package (pip install yfinance),
which handles Yahoo's cookie and crumb requirements. Without it you still get prices and
volatility, and you type the option premium in yourself.

What each number means for the model
  spot       latest price. Used as today's stock price.
  downside   last close BEFORE the announcement date. This is the "deal breaks" price. If the news
             leaked early this is too high, so check it against the chart.
  vol        annualised volatility of daily returns over the 60 trading days before the announcement,
             a stand-in for how the stock behaved before it became a takeover target. Do not use the
             option's implied volatility here, because for a deal target it is already squashed by the deal.
"""
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

CHART = "https://query1.finance.yahoo.com/v8/finance/chart/%s?%s"
UA = "Mozilla/5.0 (compatible; DealRadar research prototype)"


class MarketError(Exception):
    pass


def chart(ticker, start, end, timeout=15):
    """Daily closes as [(date, close)] plus Yahoo's descriptive metadata for the ticker."""
    q = urllib.parse.urlencode({"period1": int(datetime(start.year, start.month, start.day, tzinfo=timezone.utc).timestamp()),
                                "period2": int(datetime(end.year, end.month, end.day, tzinfo=timezone.utc).timestamp()) + 86400,
                                "interval": "1d", "events": "div,splits"})
    req = urllib.request.Request(CHART % (urllib.parse.quote(ticker), q), headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise MarketError("Yahoo does not recognise the ticker %s" % ticker if e.code == 404 else "Yahoo returned HTTP %d for %s" % (e.code, ticker))
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        raise MarketError("Could not read Yahoo prices: %s" % e)
    res = (data.get("chart", {}).get("result") or [None])[0]
    if not res or not res.get("timestamp"):
        raise MarketError("Yahoo has no price history for %s" % ticker)
    closes = res["indicators"]["quote"][0]["close"]
    out = []
    for ts, c in zip(res["timestamp"], closes):
        if c is not None:
            out.append((datetime.fromtimestamp(ts, tz=timezone.utc).date(), float(c)))
    return out, res.get("meta", {})


def history(ticker, start, end, timeout=15):
    """Daily closes as a list of (date, close), oldest first."""
    return chart(ticker, start, end, timeout)[0]


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
    """Nearest listed option to the requested strike and days to expiry, via yfinance if installed."""
    try:
        import yfinance as yf
    except ImportError:
        return None, "Install yfinance (pip install yfinance) to pull option quotes."
    try:
        t = yf.Ticker(ticker)
        exps = t.options
        if not exps:
            return None, "Yahoo lists no options for %s." % ticker
        today = date.today()
        exp = min(exps, key=lambda e: abs((date.fromisoformat(e) - today).days - days))
        chain = t.option_chain(exp)
        df = chain.calls if kind == "call" else chain.puts
        row = df.iloc[(df["strike"] - strike).abs().argsort().iloc[0]]
        bid, ask, last = float(row.get("bid") or 0), float(row.get("ask") or 0), float(row.get("lastPrice") or 0)
        premium = round((bid + ask) / 2, 2) if bid > 0 and ask > 0 else round(last, 2)
        return {"expiry": exp, "days": max(1, (date.fromisoformat(exp) - today).days), "strike": float(row["strike"]),
                "bid": bid, "ask": ask, "last": last, "premium": premium, "iv": float(row.get("impliedVolatility") or 0),
                "openInterest": int(row.get("openInterest") or 0), "volume": int(row.get("volume") or 0)}, None
    except Exception as e:   # yfinance raises many kinds of errors when Yahoo changes something
        return None, "Option lookup failed: %s" % e


def snapshot(ticker, filed_on, kind="call", strike=None, days=60):
    start = (filed_on or date.today()) - timedelta(days=130)
    series = history(ticker, start, date.today())
    out = stats(series, filed_on or date.today())
    out["ticker"] = ticker
    out["option"], out["optionNote"] = (contract(ticker, kind, strike, days) if strike else (None, "Enter a strike to look up an option."))
    return out


def history_many(tickers, days=504, benchmark="SPY"):
    """Aligned daily closes for several tickers plus the market benchmark.

    Only dates on which every ticker and the benchmark have a price are kept, so the returns line up.
    Tickers Yahoo cannot find are left out and named in "errors".
    """
    end = date.today()
    start = end - timedelta(days=int(days * 1.5) + 10)
    series, errors = {}, {}
    for t in [benchmark] + [x for x in tickers if x != benchmark]:
        try:
            series[t] = dict(history(t, start, end))
        except MarketError as e:
            errors[t] = str(e)
    if benchmark not in series:
        raise MarketError("Could not load the %s benchmark: %s" % (benchmark, errors.get(benchmark, "unknown error")))
    common = sorted(set.intersection(*[set(s) for s in series.values()]))[-days:]
    if len(common) < 60:
        raise MarketError("Fewer than 60 shared trading days across these tickers.")
    return {"dates": [d.isoformat() for d in common], "closes": {t: [s[d] for d in common] for t, s in series.items()}, "errors": errors}


_bench_cache = {"at": 0.0, "series": None}


def _benchmark(start, end):
    import time
    if not _bench_cache["series"] or time.time() - _bench_cache["at"] > 3600:
        _bench_cache["series"], _bench_cache["at"] = dict(history("SPY", start, end)), time.time()
    return _bench_cache["series"]


def beta_vs(series, bench):
    """Slope of the stock's daily returns on the market's, over up to the last 504 shared days. None if too little data."""
    sd = dict(series)
    days = sorted(set(sd) & set(bench))[-505:]
    if len(days) < 61:
        return None
    r = [(sd[b] / sd[a] - 1, bench[b] / bench[a] - 1) for a, b in zip(days, days[1:])]
    mx, my = sum(x for _, x in r) / len(r), sum(y for y, _ in r) / len(r)
    var = sum((x - mx) ** 2 for _, x in r)
    return None if var <= 0 else sum((x - mx) * (y - my) for y, x in r) / var


def quote(ticker, kind=None, strike=None, days=60):
    """Everything the portfolio table fills in for a ticker: name, price, beta and, for an option row, a quote."""
    end = date.today()
    start = end - timedelta(days=760)
    series, meta = chart(ticker, start, end)
    out = {"ticker": ticker, "name": meta.get("longName") or meta.get("shortName") or ticker,
           "price": meta.get("regularMarketPrice") or series[-1][1], "currency": meta.get("currency"),
           "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"), "kind": meta.get("instrumentType"),
           "high52": meta.get("fiftyTwoWeekHigh"), "low52": meta.get("fiftyTwoWeekLow"), "asOf": series[-1][0].isoformat(),
           "beta": None, "betaSource": None, "betaReported": None, "sector": None, "marketCap": None, "days": len(series)}
    try:
        out["beta"] = beta_vs(series, _benchmark(start, end))
        if out["beta"] is not None:
            out["betaSource"] = "computed from daily returns against SPY"
    except MarketError:
        pass
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        out["betaReported"] = info.get("beta")
        out["sector"] = info.get("sector")
        out["marketCap"] = info.get("marketCap")
        if out["beta"] is None and out["betaReported"] is not None:
            out["beta"], out["betaSource"] = out["betaReported"], "reported by Yahoo"
    except Exception:
        pass
    out["option"], out["optionNote"] = (None, None)
    if kind in ("call", "put") and strike:
        out["option"], out["optionNote"] = contract(ticker, kind, strike, days)
    return out
