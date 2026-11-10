"""Black-Scholes option values and an acquisition scenario that uses them.

This module does not estimate the chance a company is acquired. The probability
in the scenario is an input. It is not read from the filing heuristic, and a
missing probability is left missing.
"""
import math


def _number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def year_fraction(days):
    days = _number(days)
    if days is None:
        return None
    return days / 365.0


def price(spot, strike, years, rate, volatility, dividend=0.0):
    """European call and put, with d1, d2, and the shared Greeks.

    Theta is the change per year. Vega is the change for a 1.0 move in volatility,
    not a one-point move. Invalid inputs return None instead of a substituted price.
    """
    spot = _number(spot)
    strike = _number(strike)
    years = _number(years)
    rate = _number(rate)
    volatility = _number(volatility)
    dividend = 0.0 if _number(dividend) is None else _number(dividend)
    if None in (spot, strike, years, rate, volatility):
        return None
    if spot <= 0 or strike <= 0 or years < 0 or volatility < 0:
        return None
    if years == 0 or volatility == 0:
        call = max(spot * math.exp(-dividend * years) - strike * math.exp(-rate * years), 0.0)
        put = max(strike * math.exp(-rate * years) - spot * math.exp(-dividend * years), 0.0)
        return {
            "d1": None, "d2": None, "call": call, "put": put,
            "delta_call": None, "delta_put": None, "gamma": None,
            "theta_call": None, "theta_put": None, "vega": None,
            "expired_or_zero_vol": True,
        }
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - dividend + 0.5 * volatility * volatility) * years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t
    discount_spot = math.exp(-dividend * years)
    discount_strike = math.exp(-rate * years)
    pdf = _pdf(d1)
    call = spot * discount_spot * _cdf(d1) - strike * discount_strike * _cdf(d2)
    put = strike * discount_strike * _cdf(-d2) - spot * discount_spot * _cdf(-d1)
    delta_call = discount_spot * _cdf(d1)
    delta_put = discount_spot * (_cdf(d1) - 1.0)
    gamma = discount_spot * pdf / (spot * volatility * sqrt_t)
    vega = spot * discount_spot * pdf * sqrt_t
    theta_call = (-spot * discount_spot * pdf * volatility / (2.0 * sqrt_t)
                  - rate * strike * discount_strike * _cdf(d2)
                  + dividend * spot * discount_spot * _cdf(d1))
    theta_put = (-spot * discount_spot * pdf * volatility / (2.0 * sqrt_t)
                 + rate * strike * discount_strike * _cdf(-d2)
                 - dividend * spot * discount_spot * _cdf(-d1))
    return {
        "d1": d1, "d2": d2, "call": call, "put": put,
        "delta_call": delta_call, "delta_put": delta_put, "gamma": gamma,
        "theta_call": theta_call, "theta_put": theta_put, "vega": vega,
        "expired_or_zero_vol": False,
    }


def _side(result, kind):
    if result is None:
        return None
    if kind == "call":
        return result["call"]
    if kind == "put":
        return result["put"]
    return None


def implied_volatility(market_price, spot, strike, years, rate, kind, dividend=0.0):
    """Volatility that matches an observed European price. No price, no volatility."""
    market_price = _number(market_price)
    kind = "put" if kind == "put" else "call" if kind == "call" else None
    if market_price is None or market_price < 0 or kind is None:
        return None
    lower = price(spot, strike, years, rate, 0.0, dividend)
    upper_spot = _number(spot)
    upper_strike = _number(strike)
    years_n = _number(years)
    rate_n = _number(rate)
    dividend_n = 0.0 if _number(dividend) is None else _number(dividend)
    if lower is None or None in (upper_spot, upper_strike, years_n, rate_n):
        return None
    floor = _side(lower, kind)
    if kind == "call":
        ceiling = upper_spot * math.exp(-dividend_n * max(years_n, 0.0))
    else:
        ceiling = upper_strike * math.exp(-rate_n * max(years_n, 0.0))
    if market_price < floor - 1e-8 or market_price > ceiling + 1e-8:
        return {"volatility": None, "converged": False, "iterations": 0,
                "reason": "The observed price is outside the no-arbitrage bounds."}
    low, high = 1e-6, 5.0
    for iteration in range(1, 81):
        mid = 0.5 * (low + high)
        value = _side(price(spot, strike, years, rate, mid, dividend), kind)
        if value is None:
            return None
        if abs(value - market_price) < 1e-8 or high - low < 1e-8:
            return {"volatility": mid, "converged": True, "iterations": iteration, "reason": None}
        if value > market_price:
            high = mid
        else:
            low = mid
    return {"volatility": 0.5 * (low + high), "converged": False, "iterations": 80,
            "reason": "Implied volatility did not converge."}


def _level(assumptions):
    consideration = assumptions.get("consideration")
    if consideration == "cash":
        return _number(assumptions.get("acquisition_price")), "acquisition_price"
    if consideration == "stock":
        ratio = _number(assumptions.get("exchange_ratio"))
        acquirer = _number(assumptions.get("acquirer_price"))
        if ratio is None or acquirer is None or ratio <= 0 or acquirer <= 0:
            return None, "exchange_ratio and acquirer_price"
        return ratio * acquirer, None
    if consideration == "mixed":
        cash = _number(assumptions.get("cash_amount"))
        ratio = _number(assumptions.get("exchange_ratio"))
        acquirer = _number(assumptions.get("acquirer_price"))
        if None in (cash, ratio, acquirer) or cash < 0 or ratio < 0 or acquirer <= 0:
            return None, "cash_amount, exchange_ratio, and acquirer_price"
        return cash + ratio * acquirer, None
    return None, "consideration"


def acquisition_option_value(assumptions):
    """V = p * C_deal + (1 - p) * C_no_deal, with p supplied by the caller.

    C_deal splits an announced deal into completion and failure. The completion
    price is Black-Scholes at the assumed acquisition value. If the option expires
    before the assumed close, that value is not used.
    """
    assumptions = assumptions or {}
    required = (
        "spot", "strike", "rate", "kind", "standalone_volatility", "deal_volatility",
        "acquisition_probability", "failure_probability", "consideration",
        "days_to_expiration", "days_to_close",
    )
    missing = [key for key in required if assumptions.get(key) is None]
    kind = assumptions.get("kind")
    if kind not in ("call", "put"):
        missing.append("kind")
    probability = _number(assumptions.get("acquisition_probability"))
    failure = _number(assumptions.get("failure_probability"))
    if probability is None or not 0.0 <= probability <= 1.0:
        missing.append("acquisition_probability")
    if failure is None or not 0.0 <= failure <= 1.0:
        missing.append("failure_probability")
    years = year_fraction(assumptions.get("days_to_expiration"))
    close_years = year_fraction(assumptions.get("days_to_close"))
    if years is None or close_years is None or years < 0 or close_years < 0:
        missing.append("days_to_expiration")
    known_on = assumptions.get("known_on")
    as_of = assumptions.get("as_of")
    if known_on is not None and as_of is not None and known_on > as_of:
        return {"expected": None, "missing": ["known_on"],
                "reason": "An assumption is dated after the valuation date."}
    level, level_gap = _level(assumptions)
    if level is None:
        missing.append(level_gap)
    if failure not in (None,) and failure > 0 and assumptions.get("downside") is None:
        missing.append("downside")
    if missing:
        return {"expected": None, "missing": missing, "reason": "An explicit assumption is missing."}

    dividend = assumptions.get("dividend") or 0.0
    standalone = price(assumptions["spot"], assumptions["strike"], years, assumptions["rate"],
                       assumptions["standalone_volatility"], dividend)
    no_deal = _side(standalone, kind)
    if no_deal is None:
        return {"expected": None, "missing": ["spot"], "reason": "The standalone price is not defined."}
    expiration_days = _number(assumptions.get("days_to_expiration"))
    close_days = _number(assumptions.get("days_to_close"))
    announcement_days = _number(assumptions.get("days_to_announcement"))
    if announcement_days is not None and expiration_days < announcement_days:
        return {
            "expected": no_deal, "no_deal": no_deal, "deal": no_deal, "completed": no_deal,
            "break_value": None, "probability": probability, "probability_applied": False,
            "reason": "The option expires before the assumed announcement, so the deal terms are not in the payoff.",
            "black_scholes": standalone,
        }
    if expiration_days < close_days:
        return {
            "expected": None, "no_deal": no_deal, "deal": None, "completed": None,
            "break_value": None, "probability": probability, "probability_applied": False,
            "reason": "The assumed close is after expiration, so the acquisition price is not an option payoff.",
            "black_scholes": standalone,
        }
    completed_price = price(level, assumptions["strike"], years, assumptions["rate"],
                            assumptions["deal_volatility"], dividend)
    completed = _side(completed_price, kind)
    downside = assumptions["spot"] if failure == 0 else assumptions.get("downside")
    break_price = price(downside, assumptions["strike"], years, assumptions["rate"],
                        assumptions["standalone_volatility"], dividend)
    break_value = _side(break_price, kind)
    if completed is None or break_value is None:
        return {"expected": None, "missing": ["acquisition_value"], "reason": "A scenario price is not defined."}
    deal = (1.0 - failure) * completed + failure * break_value
    expected = probability * deal + (1.0 - probability) * no_deal
    return {
        "expected": expected, "no_deal": no_deal, "deal": deal, "completed": completed,
        "break_value": break_value, "probability": probability, "failure_probability": failure,
        "probability_applied": True, "acquisition_level": level, "reason": None,
        "black_scholes": standalone,
    }


def compare_values(assumptions):
    """Market price, Black-Scholes, and the acquisition-weighted value.

    Expected return is omitted when the market price or the transaction cost is absent.
    """
    valued = acquisition_option_value(assumptions or {})
    market = _number((assumptions or {}).get("market_price"))
    cost = _number((assumptions or {}).get("transaction_cost_per_share"))
    out = {
        "market_price": market,
        "black_scholes": valued.get("no_deal"),
        "acquisition_value": valued.get("expected"),
        "expected_return": None,
        "downside_value": valued.get("break_value") if valued.get("break_value") is not None else valued.get("no_deal"),
        "downside_return": None,
        "uncertainty_low": None,
        "uncertainty_high": None,
        "reason": valued.get("reason"),
        "notes": [],
    }
    if market is None:
        out["notes"].append("No observed option price was supplied.")
    if cost is None:
        out["notes"].append("No transaction cost was supplied.")
    if market is not None and market > 0 and cost is not None and cost >= 0 and valued.get("expected") is not None:
        entry = market + cost
        out["expected_return"] = (valued["expected"] - entry) / entry
        if out["downside_value"] is not None:
            out["downside_return"] = (out["downside_value"] - entry) / entry
    low = _number((assumptions or {}).get("probability_low"))
    high = _number((assumptions or {}).get("probability_high"))
    if low is not None and high is not None and 0.0 <= low <= high <= 1.0 and valued.get("probability_applied"):
        for label, probability in (("uncertainty_low", low), ("uncertainty_high", high)):
            altered = dict(assumptions)
            altered["acquisition_probability"] = probability
            again = acquisition_option_value(altered)
            out[label] = again.get("expected")
    elif low is not None or high is not None:
        out["notes"].append("The probability range was not used.")
    return out
