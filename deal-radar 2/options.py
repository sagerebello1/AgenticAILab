"""Expiration math and research labels for long calls and puts.

No options-chain source is called from here. On 19 October 2026,
https://query1.finance.yahoo.com/v7/finance/options/PAG and the query2 host
both returned HTTP 401 Unauthorized. Yahoo does not publish a free options API
with stated terms, and that 401 is an access restriction, not a blank to fill in.
Premiums, Greeks, and contract symbols stay empty until someone types them.
"""
import math
from datetime import datetime, timezone

CHAIN = {
    "available": False,
    "provider": "Yahoo Finance options endpoint",
    "checked": "2026-10-19",
    "http": 401,
    "official": False,
    "billing": False,
    "note": "Yahoo's options endpoint refused the request with HTTP 401. No free official options-chain API was found. Type the bid and ask from a quote you can see. Nothing here is a live chain.",
}

# Sources considered on 19 October 2026. None is called. "used" stays false.
AUDIT = [
    {"name": "Yahoo Finance options", "used": False, "reason": "query1 and query2 returned HTTP 401. Unofficial, and the refusal is not bypassed."},
    {"name": "yfinance", "used": False, "reason": "It works around Yahoo's session check. That is not used."},
    {"name": "Cboe DataShop and LiveVol", "used": False, "reason": "Official options API. Signup and usage pricing. Not free."},
    {"name": "Cboe delayed quote JSON on cdn.cboe.com", "used": False, "reason": "Observed behind cboe.com quote pages. Not a documented developer API, so it is not scraped."},
    {"name": "Alpha Vantage options", "used": False, "reason": "Real-time and historical options functions are premium. A free key does not include them."},
    {"name": "Polygon, Databento, Tradier, Alpaca", "used": False, "reason": "Account, brokerage, or a paid plan. Not added."},
]

STANDARD_MULTIPLIER = 100


def _num(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def catalyst(note, flags, filing_status):
    """Name the event from text the filing reader already produced. Do not upgrade a guess."""
    text = (note or "").lower()
    flags = flags or {}
    if "ends a merger" in text:
        kind, label = "termination", "Deal termination"
    elif "already closed" in text:
        kind, label = "completed", "Deal completed"
    elif flags.get("secondRequest") or flags.get("foreign"):
        kind, label = "regulatory", "Regulatory development"
    elif flags.get("financingCondition") is True:
        kind, label = "financing", "Financing condition"
    elif flags.get("vote"):
        kind, label = "vote", "Shareholder vote mentioned"
    elif "amends an earlier" in text:
        kind, label = "amendment", "Amendment, price not restated"
    elif "another company" in text or "stock consideration" in text:
        kind, label = "other_deal", "Filing is not a cash bid for this stock"
    elif filing_status == "extracted":
        kind, label = "terms_quoted", "Cash price quoted from a filing"
    else:
        kind, label = "unverified", "Merger filing, terms not verified"
    confirmed = filing_status == "extracted" and kind == "terms_quoted"
    return {"kind": kind, "label": label, "confirmed": confirmed}


def greeks(spot, strike, days, rate, iv, kind):
    """Black-Scholes Greeks from an implied volatility the user supplied.

    Returned only when every input is present. They are calculated, not exchange values.
    Vega is the change per share for a 1 percentage-point move in volatility.
    Theta is the change per share per calendar day.
    """
    spot, strike, days, iv = _num(spot), _num(strike), _num(days), _num(iv)
    rate = 0.0 if _num(rate) is None else _num(rate)
    if None in (spot, strike, days, iv) or min(spot, strike, days, iv) <= 0:
        return None
    years = days / 365.0
    sigma = iv if iv <= 3 else iv / 100.0
    if sigma <= 0:
        return None
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * years) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    pdf = _norm_pdf(d1)
    call = kind != "put"
    delta = _norm_cdf(d1) if call else _norm_cdf(d1) - 1.0
    gamma = pdf / (spot * sigma * sqrt_t)
    vega = spot * pdf * sqrt_t * 0.01
    theta = -(spot * pdf * sigma) / (2.0 * sqrt_t)
    if call:
        theta -= rate * strike * math.exp(-rate * years) * _norm_cdf(d2)
    else:
        theta += rate * strike * math.exp(-rate * years) * _norm_cdf(-d2)
    theta /= 365.0
    return {
        "source": "calculated",
        "note": "Calculated from the implied volatility you entered. Not an exchange Greek.",
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
    }


def _payoff(kind, strike, premium, price, multiplier):
    intrinsic = max(price - strike, 0.0) if kind == "call" else max(strike - price, 0.0)
    return (intrinsic - premium) * multiplier


def analyze_contract(kind, raw, context):
    """One long call or long put. Missing quotes stay missing."""
    kind = "put" if kind == "put" else "call"
    strike = _num(raw.get("strike"))
    days = _num(raw.get("days"))
    bid = _num(raw.get("bid"))
    ask = _num(raw.get("ask"))
    iv = _num(raw.get("iv"))
    multiplier = _num(raw.get("multiplier"))
    deliverable = _num(raw.get("deliverable"))
    if multiplier is None:
        multiplier = STANDARD_MULTIPLIER
    if deliverable is None:
        deliverable = STANDARD_MULTIPLIER
    spot = _num(context.get("spot"))
    offer = _num(context.get("offer"))
    downside = _num(context.get("downside"))
    event = context.get("catalyst") or {}
    errors = []
    if strike is None or strike <= 0:
        errors.append("Strike is missing.")
    if days is None or days <= 0:
        errors.append("Days to expiration are missing.")
    if multiplier <= 0 or deliverable <= 0:
        errors.append("Multiplier and deliverable must be positive.")
    nonstandard = deliverable != STANDARD_MULTIPLIER or multiplier != STANDARD_MULTIPLIER
    premium = None
    if ask is None or ask <= 0:
        errors.append("Ask is missing, so there is no entry cost for a purchase.")
    elif bid is not None and bid > ask:
        errors.append("Bid is above the ask.")
    else:
        premium = ask
    quoted_at = raw.get("quotedAt")
    if quoted_at:
        try:
            stamp = datetime.fromisoformat(str(quoted_at).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            if age > 20 * 60:
                errors.append("The quote timestamp is more than 20 minutes old, so it is not used.")
                premium = None
        except ValueError:
            errors.append("Quote timestamp could not be read.")
            premium = None
    result = {
        "kind": kind,
        "quoteState": "manual" if premium is not None else "unavailable",
        "liveOpportunity": False,
        "strike": strike,
        "days": days,
        "bid": bid,
        "ask": ask,
        "premium": premium,
        "premiumNote": "Entry cost uses the ask. A midpoint is not treated as executable." if premium is not None else "No ask was entered.",
        "multiplier": multiplier,
        "deliverable": deliverable,
        "nonstandard": nonstandard,
        "nonstandardNote": "Deliverable or multiplier is not the standard 100. Confirm the contract before using the dollar figures." if nonstandard else "",
        "iv": iv if iv and iv > 0 else None,
        "greeks": None,
        "breakEven": None,
        "maxLoss": None,
        "cost": None,
        "scenarios": [],
        "signals": [],
        "errors": errors,
    }
    if iv and iv > 0 and not errors:
        result["greeks"] = greeks(spot, strike, days, context.get("rate") or 0.045, iv, kind)
    elif not errors:
        result["greeks"] = None
    if errors or premium is None or strike is None:
        if any("Ask is missing" in e for e in errors):
            result["signals"].append({"label": "Insufficient options data", "reason": "A long contract needs an ask. No chain was retrieved, and none was typed in."})
        return result
    result["breakEven"] = round(strike + premium, 4) if kind == "call" else round(strike - premium, 4)
    result["maxLoss"] = round(premium * multiplier, 2)
    result["cost"] = result["maxLoss"]
    prices = []
    for name, price in (("If the deal dies", downside), ("Stock today", spot), ("If the deal closes at the offer", offer)):
        if price is not None and price > 0:
            prices.append((name, price))
    result["scenarios"] = [{
        "name": name,
        "price": price,
        "perShare": round(_payoff(kind, strike, premium, price, 1), 4),
        "contract": round(_payoff(kind, strike, premium, price, multiplier), 2),
        "label": "Expiration payoff if the stock is at this price. Not a value before expiration, and not a prediction.",
    } for name, price in prices]
    signals = []
    if event.get("kind") in ("termination", "completed", "regulatory") or (days is not None and days <= 14):
        signals.append({"label": "High event risk", "reason": "The filing points to a termination, a closing, a regulator, or the contract expires within 14 days. The premium can change faster than the model."})
    if event.get("kind") in ("termination", "completed"):
        signals.append({"label": "Deal status changed", "reason": event.get("label") or "The latest filing does not describe an open cash offer."})
    if bid is not None and ask and (bid <= 0 or (ask - bid) / ask > 0.25):
        signals.append({"label": "Poor liquidity", "reason": "The bid is missing or the bid/ask gap is wider than a quarter of the ask. The ask may not be a price you can lift in size."})
    volume, oi = _num(raw.get("volume")), _num(raw.get("openInterest"))
    if volume is not None and oi is not None and volume < 10 and oi < 50:
        signals.append({"label": "Poor liquidity", "reason": "Volume and open interest on the numbers you entered are thin."})
    if result["iv"] is not None and (result["iv"] if result["iv"] <= 3 else result["iv"] / 100.0) >= 0.80:
        signals.append({"label": "Elevated implied volatility", "reason": "The implied volatility you entered is 80% or higher. That describes your input. It is not a live volatility surface."})
    offer_pay = _payoff(kind, strike, premium, offer, multiplier) if offer is not None else None
    if not event.get("confirmed"):
        signals.append({"label": "No verified edge", "reason": "The filing was not read as a verified cash offer for this stock, so a contract payoff is not an opportunity."})
    elif offer_pay is not None and offer_pay <= 0 and kind == "call":
        signals.append({"label": "No verified edge", "reason": "The call's expiration break-even is at or above the cash offer. If the stock stops at the offer, this long call does not finish ahead of the premium."})
    elif offer_pay is not None and offer_pay <= 0:
        signals.append({"label": "No verified edge", "reason": "At the cash offer, this long put's expiration payoff does not cover the ask."})
    elif event.get("confirmed"):
        signals.append({"label": "Research candidate", "reason": "A cash price was quoted from a filing and an ask was typed in. The ask is not a retrieved quote, so this is not a live opportunity and not a recommendation."})
    result["liveOpportunity"] = False
    result["signals"] = signals
    return result


def analyze(payload):
    """Compare one call and one put. The close probability is not turned into an expected return."""
    context = {
        "spot": payload.get("spot"),
        "offer": payload.get("offer"),
        "downside": payload.get("downside"),
        "rate": payload.get("rate") or 0.045,
        "catalyst": payload.get("catalyst") or catalyst(payload.get("note"), payload.get("flags"), payload.get("filingStatus")),
    }
    call = analyze_contract("call", payload.get("call") or {}, context)
    put = analyze_contract("put", payload.get("put") or {}, context)
    return {
        "chain": CHAIN,
        "catalyst": context["catalyst"],
        "pClose": payload.get("pClose"),
        "pCloseNote": "Rules-based estimate from the filing. It is not multiplied by the option payoff, and it is not a statistically validated prediction.",
        "call": call,
        "put": put,
        "placesTrades": False,
    }
