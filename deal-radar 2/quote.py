"""Stock bid and ask from the chance an announced cash deal closes.

Two chances stay separate. The filing chance is built in log-odds from the same
adjustments as terms.estimate_probabilities, starting at the 90% base rate
(nine in ten announced deals close). The market chance is inverted from the
stock price. The bid and the ask sit one risk charge away from the value that
your chance implies. Trade only when the stock is outside that band.

Live prices and headlines, when requested, come from Yahoo's public chart and
RSS endpoints. Those need no key. This module does not call Dealroom or any
paid model API.
"""
import math
from datetime import date, timedelta

import news
import sample_data

BASE_P = 0.90
SCALE = BASE_P * (1.0 - BASE_P)  # one probability point, in log-odds, at the base rate
DEFAULTS = {"rate": 0.045, "sigma": 0.04, "hurdle": 0.08, "capital": 100000.0, "risk": 0.02, "notional": 0.15}


class InputError(Exception):
    """The request itself is missing a number or names an unknown sample."""


class UpstreamError(Exception):
    """A free data source did not answer."""


def logit(p):
    p = min(0.999, max(0.001, p))
    return math.log(p / (1.0 - p))


def sigmoid(z):
    return 1.0 / (1.0 + math.exp(-z))


def _pct_or_fraction(value, default, name):
    """Accept 0.04 or 4 for a 4% input. Numbers above 1 are percents."""
    if value is None or value == "":
        return default
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise InputError("%s must be a number." % name)
    if abs(x) > 1:
        x = x / 100.0
    return x


def _chance(value):
    """Accept 0.466 or 46.6. Blank means 'use the filing'."""
    if value is None or value == "":
        return None
    try:
        p = float(value)
    except (TypeError, ValueError):
        raise InputError("p must be a number, as a fraction (0.47) or a percent (47).")
    if p > 1:
        p = p / 100.0
    return min(0.99, max(0.01, p))


def _as_list(value):
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [part.strip() for part in str(value).split(",") if part.strip()]


def _yes(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _financing(value):
    """True: the deal depends on financing. False: it explicitly does not. None: unstated."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "depends"):
        return True
    if text in ("0", "false", "no", "n", "none"):
        return False
    return None


def _first(params, *keys):
    for key in keys:
        if key in params and params[key] not in (None, ""):
            return params[key]
    return None


def normalize(params):
    """Flatten a query dict (lists) or a JSON object down to single values."""
    out = {}
    for key, value in (params or {}).items():
        if isinstance(value, list):
            value = value[0] if value else None
        if value is not None and value != "":
            out[key] = value
    return out


def close_probability(flags):
    """Filing chance in log-odds, plus the old additive score for comparison.

    flags: hsr, secondRequest, foreign (list), other (list), financingCondition
    (True / False / None), tender, vote, goShop, consideration ('cash' or 'stock').
    """
    drivers = [{"label": "Announced deals close about 9 in 10 times", "logOdds": logit(BASE_P)}]
    z = logit(BASE_P)
    old = 0.93

    def push(label, points):
        nonlocal z, old
        shift = points / SCALE
        z += shift
        old += points
        drivers.append({"label": label, "logOdds": shift})

    if flags.get("hsr"):
        push("US antitrust filing (HSR)", -0.01)
    if flags.get("secondRequest"):
        push("Second request from regulators", -0.10)
    foreign = _as_list(flags.get("foreign"))
    if foreign:
        push("Foreign approvals: " + ", ".join(foreign), -min(0.03 * len(foreign), 0.09))
    other = _as_list(flags.get("other"))
    if other:
        push("Sector approvals: " + ", ".join(other), -min(0.03 * len(other), 0.06))
    fin = flags.get("financingCondition")
    if fin is True:
        push("Closing depends on financing", -0.06)
    elif fin is False:
        push("No financing condition", 0.01)
    if flags.get("tender"):
        push("Tender offer", 0.02)
    elif flags.get("vote"):
        push("Shareholder vote required", -0.01)
    if flags.get("goShop"):
        push("Go-shop period", -0.01)
    if flags.get("consideration") == "stock":
        push("Paid in the acquirer's stock", -0.02)

    running = 0.0
    for row in drivers:
        running += row["logOdds"]
        row["logOdds"] = round(row["logOdds"], 4)
        row["running"] = round(sigmoid(running), 4)
    return {"close": sigmoid(z), "legacy": min(0.98, max(0.35, old)), "drivers": drivers}


def _flags_from(params, deal=None):
    flags = {}
    if deal:
        src = deal.get("flags") or {}
        flags = {
            "hsr": src.get("hsr"),
            "secondRequest": src.get("secondRequest"),
            "foreign": src.get("foreign") or [],
            "other": src.get("other") or [],
            "financingCondition": src.get("financingCondition"),
            "tender": src.get("tender"),
            "vote": src.get("vote"),
            "goShop": src.get("goShop"),
            "consideration": deal.get("consideration"),
        }
    if _first(params, "hsr") is not None:
        flags["hsr"] = _yes(params["hsr"])
    if _first(params, "secondRequest", "second") is not None:
        flags["secondRequest"] = _yes(_first(params, "secondRequest", "second"))
    if _first(params, "foreign") is not None:
        flags["foreign"] = _as_list(params["foreign"])
    if _first(params, "other") is not None:
        flags["other"] = _as_list(params["other"])
    if _first(params, "financingCondition", "financing") is not None:
        flags["financingCondition"] = _financing(_first(params, "financingCondition", "financing"))
    if _first(params, "tender") is not None:
        flags["tender"] = _yes(params["tender"])
    if _first(params, "vote") is not None:
        flags["vote"] = _yes(params["vote"])
    if _first(params, "goShop", "goshop") is not None:
        flags["goShop"] = _yes(_first(params, "goShop", "goshop"))
    if _first(params, "consideration") is not None:
        flags["consideration"] = str(params["consideration"]).strip().lower()
    elif _yes(params.get("stock")):
        flags["consideration"] = "stock"
    return flags


def _find_sample(deal_id):
    for deal in sample_data.sample_deals():
        if deal["id"] == deal_id:
            return deal
    return None


def _num(params, default, *keys):
    raw = _first(params, *keys)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise InputError("%s must be a number." % keys[0])


def _market_from_yahoo(ticker, filed_on):
    """Spot and pre-announcement close from Yahoo's chart endpoint. No API key."""
    import market
    start = (filed_on or date.today()) - timedelta(days=160)
    try:
        series = market.history(ticker, start, date.today() + timedelta(days=1))
        stats = market.stats(series, filed_on or date.today())
    except market.MarketError as e:
        raise UpstreamError(str(e))
    if stats.get("downside") is None:
        raise UpstreamError("Yahoo returned a price for %s but no close before the filing date." % ticker)
    return stats


def _news_from_yahoo(ticker, names):
    """Headline nudge in log-odds from Yahoo's public RSS feed. No API key."""
    try:
        return news.for_ticker(ticker, names)
    except news.NewsError as e:
        raise UpstreamError(str(e))


def respond(params, live=False):
    """Build one quote. `params` is a query dict or a JSON object.

    Pass id=s1..s5 to start from a sample deal. Pass offer, spot, downside and
    days to price any cash deal. With live=True, a ticker fills any missing
    spot or break price from Yahoo, and news=1 applies the free headline nudge.
    """
    params = normalize(params)
    deal = None
    deal_id = _first(params, "id", "deal")
    if deal_id:
        deal = _find_sample(str(deal_id))
        if not deal:
            raise InputError("Unknown sample id '%s'. Use s1, s2, s3, s4 or s5." % deal_id)

    offer = _num(params, deal["offer"] if deal else None, "offer")
    spot = _num(params, (deal or {}).get("market", {}).get("spot") if deal else None, "spot")
    downside = _num(params, (deal or {}).get("market", {}).get("downside") if deal else None, "downside")
    days = _num(params, deal.get("daysToClose") if deal else None, "days", "daysToClose")
    ticker = _first(params, "ticker") or (deal or {}).get("ticker")
    filed_raw = _first(params, "filedOn")
    filed_on = None
    if filed_raw:
        try:
            filed_on = date.fromisoformat(str(filed_raw)[:10])
        except ValueError:
            raise InputError("filedOn must be YYYY-MM-DD.")
    elif deal and deal.get("filedDaysAgo") is not None:
        filed_on = date.today() - timedelta(days=int(deal["filedDaysAgo"]))

    want_news = _yes(params.get("news")) if "news" in params else False
    sources = [{"id": "filing-rules", "name": "Local filing rules", "cost": "free"}]
    market_note = None
    filled_downside = False
    if live and ticker and (spot is None or downside is None):
        stats = _market_from_yahoo(ticker, filed_on)
        if spot is None:
            spot = stats["spot"]
        if downside is None:
            downside = stats["downside"]
            filled_downside = True
        market_note = {"asOf": stats.get("asOf"), "vol": None if stats.get("vol") is None else round(stats["vol"], 4)}
        sources.append({"id": "yahoo-chart", "name": "Yahoo Finance chart", "cost": "free",
                        "note": "Public chart endpoint. No API key."})

    if any(v is None for v in (offer, spot, downside, days)):
        raise InputError("Need offer, spot, downside and days, or a sample id (s1 to s5).")
    offer, spot, downside, days = float(offer), float(spot), float(downside), float(days)
    if min(offer, spot, downside, days) <= 0:
        raise InputError("offer, spot, downside and days must be above zero.")

    rate = _pct_or_fraction(_first(params, "rate"), DEFAULTS["rate"], "rate")
    sigma = _pct_or_fraction(_first(params, "sigma"), DEFAULTS["sigma"], "sigma")
    hurdle = _pct_or_fraction(_first(params, "hurdle"), DEFAULTS["hurdle"], "hurdle")
    try:
        capital = float(_first(params, "capital") or DEFAULTS["capital"])
    except (TypeError, ValueError):
        raise InputError("capital must be a number.")
    risk = _pct_or_fraction(_first(params, "risk"), DEFAULTS["risk"], "risk")
    notional = _pct_or_fraction(_first(params, "notional"), DEFAULTS["notional"], "notional")
    if capital <= 0 or sigma < 0 or hurdle < 0 or risk < 0 or notional < 0:
        raise InputError("capital must be positive, and sigma, hurdle, risk and notional cannot be negative.")

    scored = close_probability(_flags_from(params, deal))
    your_p = _chance(_first(params, "p", "chance"))
    p_source = "filing"
    if your_p is None:
        your_p = scored["close"]
    else:
        p_source = "override"

    news_block = None
    if want_news:
        if not ticker:
            raise InputError("news=1 needs a ticker.")
        names = [x for x in (_first(params, "name", "target") or (deal or {}).get("target"),
                             _first(params, "acquirer") or (deal or {}).get("acquirer")) if x]
        news_block = _news_from_yahoo(ticker, names)
        your_p = news.apply(your_p, news_block["adjustment"])
        p_source = p_source + "+news"
        sources.append({"id": "yahoo-rss", "name": "Yahoo Finance headlines", "cost": "free",
                        "note": "Public RSS feed. No API key. Weights are judgments, capped at ±1.5 log-odds."})

    years = days / 365.0
    pv = offer * math.exp(-rate * years)
    span = pv - downside
    if abs(span) < 1e-6:
        raise InputError("The discounted offer and the break price are the same, so the chance cannot be read from the stock.")
    p_market = (spot - downside) / span
    value = your_p * pv + (1.0 - your_p) * downside
    uncertainty = abs(span) * sigma
    hurdle_dollars = spot * hurdle * years
    charge = max(uncertainty, hurdle_dollars)
    bid = value - charge
    ask = value + charge
    if spot < bid - 1e-9:
        action = "bid"
    elif spot > ask + 1e-9:
        action = "ask"
    else:
        action = "pass"

    size = None
    if action != "pass":
        loss = (spot - downside) if action == "bid" else (offer - spot)
        if loss > 0 and spot > 0:
            shares = int(min(capital * risk / loss, capital * notional / spot))
            if shares > 0:
                size = {"shares": shares, "notional": round(shares * spot, 2),
                        "lossPerShare": round(loss, 2), "lossDollars": round(shares * loss, 2),
                        "badOutcome": "deal breaks" if action == "bid" else "deal closes"}

    if action == "bid":
        instruction = "Bid. Do not pay more than $%.2f." % bid
    elif action == "ask":
        instruction = "Ask. Do not sell cheaper than $%.2f." % ask
    else:
        instruction = "Stand aside. The stock at $%.2f is inside $%.2f to $%.2f." % (spot, bid, ask)

    outside = None
    if filled_downside and filed_on is None:
        outside = "No filing date was given, so the break price is the last close before today, not a pre-announcement price."
    elif p_market > 1:
        outside = "The stock is above the discounted offer, so the price is assuming a higher bid or a stale offer."
    elif p_market < 0:
        outside = "The stock is below the break price, so the price is assuming a worse failure than that break."

    out = {
        "freeOnly": True,
        "sources": sources,
        "pClose": round(your_p, 4),
        "pMarket": round(p_market, 4),
        "pLegacy": round(scored["legacy"], 4),
        "pSource": p_source,
        "drivers": scored["drivers"],
        "offer": round(offer, 4),
        "discountedOffer": round(pv, 4),
        "downside": round(downside, 4),
        "spot": round(spot, 4),
        "days": days,
        "rate": rate,
        "fairValue": round(value, 4),
        "uncertainty": round(uncertainty, 4),
        "hurdleDollars": round(hurdle_dollars, 4),
        "charge": round(charge, 4),
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "action": action,
        "limit": round(bid if action == "bid" else ask if action == "ask" else value, 4),
        "instruction": instruction,
        "size": size,
        "assumptions": {"sigma": sigma, "hurdle": hurdle, "capital": capital, "risk": risk, "notionalCap": notional,
                        "baseRate": BASE_P},
        "method": {
            "probability": "Log-odds sum of the filing adjustments, base rate 90%.",
            "value": "pClose * discountedOffer + (1 - pClose) * downside",
            "market": "(spot - downside) / (discountedOffer - downside)",
            "charge": "max(|discountedOffer - downside| * sigma, spot * hurdle * days / 365)",
            "bid": "fairValue - charge",
            "ask": "fairValue + charge",
        },
    }
    if deal:
        out.update(id=deal["id"], target=deal["target"], ticker=deal["ticker"],
                   acquirer=deal["acquirer"], sample=True)
    elif ticker:
        out["ticker"] = ticker
    if _first(params, "target", "name") and "target" not in out:
        out["target"] = _first(params, "target", "name")
    if market_note:
        out["market"] = market_note
    if outside:
        out["marketNote"] = outside
    if news_block:
        out["news"] = {"adjustment": news_block["adjustment"], "headlines": news_block["headlines"],
                       "flags": news_block["flags"]}
    return out


def respond_all(params):
    """Quote every fictional sample with the same policy knobs. No network."""
    shared = {k: params[k] for k in ("rate", "sigma", "hurdle", "capital", "risk", "notional") if k in normalize(params)}
    return {"freeOnly": True, "sources": [{"id": "filing-rules", "name": "Local filing rules", "cost": "free"}],
            "deals": [respond(dict(shared, id=deal["id"])) for deal in sample_data.sample_deals()]}


if __name__ == "__main__":
    alt = respond({"id": "s4"})
    assert alt["action"] == "ask", alt["action"]
    assert abs(alt["pClose"] - 0.466) < 0.01, alt["pClose"]
    assert abs(alt["pMarket"] - 0.950) < 0.01, alt["pMarket"]
    assert abs(alt["fairValue"] - 34.66) < 0.05, alt["fairValue"]
    assert abs(alt["bid"] - 32.93) < 0.05, alt["bid"]
    assert abs(alt["ask"] - 36.39) < 0.05, alt["ask"]
    book = {row["ticker"]: row["action"] for row in respond_all({})["deals"]}
    assert book == {"MARR": "pass", "QUIL": "ask", "LATH": "pass", "ALTA": "ask", "BASI": "ask"}, book
    # Bid only when the stock is cheaper than value minus the risk charge.
    rich = respond({"id": "s1", "spot": 40, "p": 0.95})
    assert rich["action"] == "bid", (rich["action"], rich["bid"], rich["spot"])
    assert rich["size"]["shares"] > 0
    print("quote OK: Altamar ask $%.2f  book %s" % (alt["ask"], book))
