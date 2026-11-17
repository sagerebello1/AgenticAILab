"""Coverage and realized put payoffs from the historical SQLite file.

A realized payoff is the put's intrinsic value at a later stored stock close.
It is not an option premium, and it is not a Black-Scholes error. Missing
terms and missing prices stay missing.
"""
from datetime import date

from historical.prices import trading_offset

VERIFIED = "t.role='target' AND IFNULL(t.is_amendment, 0)=0 AND t.duplicate_of IS NULL"
HORIZON_SESSIONS = 30
STRIKE_FRACTION = 0.80


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def load_bars(conn, ticker):
    """Stored daily closes for one ticker. A blank close is left out."""
    if not ticker:
        return []
    rows = conn.execute(
        """SELECT bar_date, close FROM historical_stock_prices
           WHERE ticker=? AND close IS NOT NULL AND close > 0
           ORDER BY bar_date, source""",
        (ticker,),
    ).fetchall()
    bars = []
    seen = set()
    for row in rows:
        try:
            day = date.fromisoformat(row["bar_date"])
        except ValueError:
            continue
        if day in seen:
            continue
        seen.add(day)
        bars.append({"date": day, "close": row["close"]})
    return bars


def _deals(conn):
    return conn.execute(
        """SELECT t.adsh, t.target_ticker, t.announcement_date, t.consideration,
                  t.offer_price, t.exchange_ratio,
                  o.price_before, o.price_day30
           FROM historical_ma_transactions t
           LEFT JOIN historical_deal_outcomes o ON o.adsh = t.adsh
           WHERE %s
           ORDER BY t.announcement_date, t.adsh""" % VERIFIED
    ).fetchall()


def measure(conn, horizon_sessions=HORIZON_SESSIONS, strike_fraction=STRIKE_FRACTION):
    """Count coverage and score research puts only where the stored inputs exist."""
    if not 0 < strike_fraction < 1:
        raise ValueError("The research strike must be below the pre-announcement close.")
    if horizon_sessions <= 0:
        raise ValueError("The later close needs a positive number of trading sessions.")
    deals = _deals(conn)
    bar_cache = {}
    coverage = {
        "verified": len(deals),
        "offer_price": 0,
        "consideration": 0,
        "consideration_cash": 0,
        "consideration_stock": 0,
        "consideration_mixed": 0,
        "consideration_other": 0,
        "exchange_ratio": 0,
        "standalone_price": 0,
        "outcome_price_before": 0,
        "outcome_price_day30": 0,
        "historical_price_ticker": 0,
        "historical_bar_on_or_before": 0,
        "historical_bar_at_horizon": 0,
    }
    missing = {
        "offer_price": 0,
        "consideration": 0,
        "exchange_ratio": 0,
        "standalone_price": 0,
        "historical_prices": 0,
        "announcement_date": 0,
        "later_close": 0,
        "not_cash": 0,
    }
    scored = []
    for deal in deals:
        offer = _num(deal["offer_price"])
        ratio = _num(deal["exchange_ratio"])
        consideration = deal["consideration"]
        if offer is not None and offer > 0:
            coverage["offer_price"] += 1
        else:
            missing["offer_price"] += 1
        if consideration in ("cash", "stock", "mixed"):
            coverage["consideration"] += 1
            coverage["consideration_" + consideration] += 1
        elif consideration:
            coverage["consideration"] += 1
            coverage["consideration_other"] += 1
        else:
            missing["consideration"] += 1
        if ratio is not None and ratio > 0:
            coverage["exchange_ratio"] += 1
        else:
            missing["exchange_ratio"] += 1
        if _num(deal["price_before"]) is not None and _num(deal["price_before"]) > 0:
            coverage["outcome_price_before"] += 1
        if _num(deal["price_day30"]) is not None and _num(deal["price_day30"]) > 0:
            coverage["outcome_price_day30"] += 1
        ticker = deal["target_ticker"]
        if ticker not in bar_cache:
            bar_cache[ticker] = load_bars(conn, ticker)
        bars = bar_cache[ticker]
        if bars:
            coverage["historical_price_ticker"] += 1
        else:
            missing["historical_prices"] += 1
        announcement = None
        if deal["announcement_date"]:
            try:
                announcement = date.fromisoformat(deal["announcement_date"])
            except ValueError:
                announcement = None
        if announcement is None:
            missing["announcement_date"] += 1
            before = later = None
        else:
            before = trading_offset(bars, announcement, -1)
            later = trading_offset(bars, announcement, horizon_sessions)
        if before is not None:
            coverage["historical_bar_on_or_before"] += 1
            coverage["standalone_price"] += 1
        else:
            missing["standalone_price"] += 1
        if later is not None:
            coverage["historical_bar_at_horizon"] += 1
        else:
            missing["later_close"] += 1
        if consideration != "cash":
            missing["not_cash"] += 1
            continue
        if offer is None or offer <= 0 or before is None or later is None:
            continue
        spot = before["close"]
        strike = strike_fraction * spot
        payoff = max(strike - later["close"], 0.0)
        scored.append({
            "adsh": deal["adsh"],
            "ticker": ticker,
            "announcement": deal["announcement_date"],
            "offer": offer,
            "spot": spot,
            "spot_date": before["date"].isoformat(),
            "strike": strike,
            "later": later["close"],
            "later_date": later["date"].isoformat(),
            "payoff": payoff,
        })
    in_the_money = sum(1 for row in scored if row["payoff"] > 0)
    return {
        "horizon_sessions": horizon_sessions,
        "strike_fraction": strike_fraction,
        "coverage": coverage,
        "missing": missing,
        "scored": scored,
        "scored_count": len(scored),
        "in_the_money": in_the_money,
        "worthless": len(scored) - in_the_money,
        "mean_payoff": (sum(row["payoff"] for row in scored) / len(scored)) if scored else None,
        "market_pricing_error": None,
        "model_payoff_error": None,
    }


def render(result):
    """Markdown coverage report. Counts come from the measurement, not from memory."""
    coverage = result["coverage"]
    missing = result["missing"]
    lines = [
        "# OTM put realized-payoff coverage",
        "",
        "This report reads the historical SQLite file. It does not price an option with Black-Scholes, and it does not call a data provider.",
        "",
        "## What was measured",
        "",
        "- Verified deals are target filings that are not amendments and not same-week duplicates.",
        "- The research put is struck at %.0f%% of the last stored close before the announcement. That strike is not a listed contract." % (100 * result["strike_fraction"]),
        "- The realized payoff is the undiscounted intrinsic value at the close %d trading sessions after the announcement: max(strike - later close, 0)." % result["horizon_sessions"],
        "- A row is scored only when the filing says cash, an offer price is stored, the prior close is stored, and the later close is stored.",
        "- No option premium is subtracted, because no historical option premium is stored.",
        "",
        "## Coverage",
        "",
        "- Verified deals: %d" % coverage["verified"],
        "- Offer price stored: %d" % coverage["offer_price"],
        "- Consideration stored: %d (cash %d, stock %d, mixed %d, other %d)" % (
            coverage["consideration"], coverage["consideration_cash"], coverage["consideration_stock"],
            coverage["consideration_mixed"], coverage["consideration_other"]),
        "- Exchange ratio stored: %d" % coverage["exchange_ratio"],
        "- Standalone stock price, the last stored close before the announcement: %d" % coverage["standalone_price"],
        "- Outcome table price before announcement: %d" % coverage["outcome_price_before"],
        "- Outcome table close 30 sessions later: %d" % coverage["outcome_price_day30"],
        "- Deals whose ticker has at least one stored daily close: %d" % coverage["historical_price_ticker"],
        "- Deals with a stored close %d sessions after the announcement: %d" % (
            result["horizon_sessions"], coverage["historical_bar_at_horizon"]),
        "",
        "## Missing",
        "",
        "- Offer price: %d" % missing["offer_price"],
        "- Consideration: %d" % missing["consideration"],
        "- Exchange ratio: %d" % missing["exchange_ratio"],
        "- Standalone stock price: %d" % missing["standalone_price"],
        "- Historical daily closes for the target ticker: %d" % missing["historical_prices"],
        "- Announcement date: %d" % missing["announcement_date"],
        "- Close %d trading sessions later: %d" % (result["horizon_sessions"], missing["later_close"]),
        "- Not a cash deal, so no payoff was calculated: %d" % missing["not_cash"],
        "",
        "## Realized payoffs",
        "",
        "- Deals scored: %d" % result["scored_count"],
        "- Finished with a positive intrinsic value: %d" % result["in_the_money"],
        "- Finished worthless: %d" % result["worthless"],
        "- Average intrinsic value per share: %s" % (
            "not calculated" if result["mean_payoff"] is None else "%.4f" % result["mean_payoff"]),
        "",
    ]
    if result["scored"]:
        lines.extend([
            "| Ticker | Announcement | Offer | Prior close | Research strike | Later close | Intrinsic |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ])
        for row in result["scored"]:
            lines.append("| %s | %s | %.2f | %.2f | %.4f | %.2f | %.4f |" % (
                row["ticker"] or "", row["announcement"], row["offer"], row["spot"],
                row["strike"], row["later"], row["payoff"]))
        lines.append("")
    lines.extend([
        "## Realized-payoff error and market pricing error",
        "",
        "- Realized-payoff error against Black-Scholes or the M&A scenario model: not computed. Both models need an implied volatility, and this database does not store one. None was filled in.",
        "- Options-market pricing error: not computed. The database has no historical option bid, ask, or implied volatility. The stored observed premium is the stock's offer premium, not an option premium, and it was not used.",
        "- The intrinsic values above are the put's stock-path payoff. They are not a statement that either model was right or wrong.",
        "",
        "## Assumptions and limits",
        "",
        "- Stock and mixed deals are counted in the coverage and are not scored. A stock deal needs the acquirer's price, which is not stored on the announcement.",
        "- The 30-session close is the same offset the dataset builder stores. It is not an option expiration date from an exchange.",
        "- The research strike is below the prior close by construction. It is one assumption, not a search over strikes.",
        "- A stored offer is used as stored. It was not dropped when it sits far from the prior close, and it was not corrected.",
        "- Daily closes are the stored Yahoo chart closes. A missing bar is not replaced.",
        "- This file does not change the live pricing engine, the server, or the screen.",
        "",
    ])
    return "\n".join(lines)
