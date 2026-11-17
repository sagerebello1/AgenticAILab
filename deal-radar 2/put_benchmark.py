"""One out-of-the-money put: plain Black-Scholes beside the existing three-scenario price.

The plain put comes from black_scholes.price. The deal-aware put comes from
pricing.scenario_value, including its weights, pinned volatilities, and the
rule for an option that expires before the expected close. The close chance
is either supplied or taken from quote.close_probability when filing flags
are supplied. A missing input stays missing.
"""
import black_scholes
import pricing
import quote


def _num(value):
    return black_scholes._number(value)


def _for_level(assumptions):
    copied = dict(assumptions)
    if copied.get("consideration") == "cash" and _num(copied.get("acquisition_price")) is None:
        offer = _num(copied.get("offer"))
        if offer is not None:
            copied["acquisition_price"] = offer
    return copied


def _level_gaps(assumptions):
    consideration = assumptions.get("consideration")
    if consideration == "cash":
        price = _num(assumptions.get("acquisition_price"))
        if price is None:
            price = _num(assumptions.get("offer"))
        return ["offer"] if price is None or price <= 0 else []
    if consideration == "stock":
        gaps = []
        ratio = _num(assumptions.get("exchange_ratio"))
        acquirer = _num(assumptions.get("acquirer_price"))
        if ratio is None or ratio <= 0:
            gaps.append("exchange_ratio")
        if acquirer is None or acquirer <= 0:
            gaps.append("acquirer_price")
        return gaps
    if consideration == "mixed":
        gaps = []
        cash = _num(assumptions.get("cash_amount"))
        ratio = _num(assumptions.get("exchange_ratio"))
        acquirer = _num(assumptions.get("acquirer_price"))
        if cash is None or cash < 0:
            gaps.append("cash_amount")
        if ratio is None or ratio <= 0:
            gaps.append("exchange_ratio")
        if acquirer is None or acquirer <= 0:
            gaps.append("acquirer_price")
        return gaps
    return ["consideration"]


def _close_probability(assumptions):
    supplied = _num(assumptions.get("p_close"))
    if supplied is not None:
        return supplied
    flags = assumptions.get("flags")
    if isinstance(flags, dict):
        return quote.close_probability(flags)["close"]
    return None


def benchmark(assumptions):
    """Price one OTM put both ways. Returns no scenario price when an input is missing."""
    assumptions = dict(assumptions or {})
    missing = []
    spot = _num(assumptions.get("spot"))
    strike = _num(assumptions.get("strike"))
    days = _num(assumptions.get("days"))
    rate = _num(assumptions.get("rate"))
    vol = _num(assumptions.get("volatility"))
    if vol is None:
        vol = _num(assumptions.get("vol"))
    downside = _num(assumptions.get("downside"))
    days_to_close = _num(assumptions.get("days_to_close"))
    premium = _num(assumptions.get("market_premium"))
    if premium is None:
        premium = _num(assumptions.get("premium"))
    if premium is not None and premium <= 0:
        premium = None

    if spot is None or spot <= 0:
        missing.append("spot")
    if strike is None or strike <= 0:
        missing.append("strike")
    if days is None or days <= 0:
        missing.append("days")
    if rate is None:
        missing.append("rate")
    if vol is None or vol <= 0:
        missing.append("volatility")
    if downside is None or downside <= 0:
        missing.append("downside")
    if days_to_close is None or days_to_close <= 0:
        missing.append("days_to_close")

    leveled = _for_level(assumptions)
    gaps = _level_gaps(leveled)
    missing.extend(gaps)
    level, _gap = black_scholes._level(leveled)
    if not gaps and (level is None or level <= 0):
        missing.append("offer")
        level = None

    p_close = _close_probability(assumptions)
    if p_close is None or not 0.0 <= p_close <= 1.0:
        missing.append("p_close")
    p_pending = _num(assumptions.get("p_pending"))
    if p_pending is None or not 0.0 <= p_pending <= 1.0:
        missing.append("p_pending")

    moneyness = None
    otm = None
    if spot is not None and strike is not None and spot > 0 and strike > 0:
        moneyness = strike / spot
        otm = strike < spot

    plain = None
    option_ready = not any(name in missing for name in ("spot", "strike", "days", "rate", "volatility"))
    if option_ready:
        priced = black_scholes.price(spot, strike, days / 365.0, rate, vol)
        plain = None if priced is None else priced["put"]

    result = {
        "kind": "put",
        "otm": otm,
        "moneyness": moneyness,
        "consideration": assumptions.get("consideration"),
        "acquisition_level": None if gaps or level is None or level <= 0 else level,
        "black_scholes": plain,
        "scenario_value": None,
        "scenarios": None,
        "difference": None,
        "market_premium": premium,
        "pricing_error_black_scholes": None,
        "pricing_error_scenario": None,
        "expires_before_close": None,
        "resolve": None,
        "p_close": None if "p_close" in missing else p_close,
        "p_pending": None if "p_pending" in missing else p_pending,
        "missing": missing,
        "reason": None,
    }
    if otm is False and not missing:
        result["reason"] = "The put is not out of the money."
        return result
    if missing or otm is not True:
        result["reason"] = "An explicit input is missing." if missing else "The put is not out of the money."
        return result

    resolve = pricing.resolved_by_expiry(days, days_to_close)
    deal = {
        "offer": level,
        "downside": downside,
        "spot": spot,
        "cash": assumptions.get("consideration") == "cash",
    }
    bump = _num(assumptions.get("bump"))
    if bump is not None:
        deal["bump"] = bump
    observed = premium if premium is not None else 0.0
    out = pricing.scenario_value(
        deal,
        {"kind": "put", "strike": strike, "days": days, "rate": rate, "vol": vol, "premium": observed},
        {"p_close": p_close, "resolve": resolve, "p_pending": p_pending},
    )
    result["scenario_value"] = out["fair"]
    result["scenarios"] = out["scenarios"]
    result["resolve"] = resolve
    result["expires_before_close"] = days < days_to_close
    result["difference"] = out["fair"] - plain
    if premium is not None:
        result["pricing_error_black_scholes"] = plain - premium
        result["pricing_error_scenario"] = out["fair"] - premium
    return result
