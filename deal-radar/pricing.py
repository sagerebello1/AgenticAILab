"""Deal-adjusted option pricing for a stock that is the target of an announced M&A deal.

A plain Black-Scholes price assumes one smooth lognormal future. A takeover target does not
have one: the stock is about to jump to the offer price, jump down to its undisturbed price,
or sit pinned in between. This module prices the contract under three scenarios and weights
them by how likely each is.

Each scenario "re-prices the stock today" to the level it would trade at in that world,
then values the contract with Black-Scholes using the volatility that world implies:

    1. Deal closes before expiry   stock -> offer (plus any bump), volatility pinned low
    2. Still unresolved at expiry  stock -> p*offer + (1-p)*downside, volatility low
    3. Deal breaks before expiry   stock -> downside price, normal volatility

The JavaScript in static/app.html mirrors this file line for line. Run `python3 pricing.py`
to check the math against known values.
"""
import math

VOL_PINNED_CASH = 0.12     # post-deal volatility when the target is bought for cash
VOL_PENDING = 0.18         # volatility of a stock that is waiting on regulators
STOCK_DEAL_VOL_FACTOR = 0.9


def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def black_scholes(spot, strike, years, rate, vol, kind="call"):
    """European option value per share."""
    if years <= 0 or vol <= 0:
        disc = strike * math.exp(-rate * max(years, 0))
        return max(spot - disc, 0.0) if kind == "call" else max(disc - spot, 0.0)
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate + vol * vol / 2.0) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = strike * math.exp(-rate * years)
    if kind == "call":
        return spot * norm_cdf(d1) - disc * norm_cdf(d2)
    return disc * norm_cdf(-d2) - spot * norm_cdf(-d1)


def resolved_by_expiry(days_to_expiry, days_to_close):
    """Chance the deal is decided (closed or broken) before the option expires.

    Compares expiry with the expected close date. Expiry at 40% of the time to close or
    less is almost certainly too early; at 130% or more it is almost certainly late enough,
    though deals do slip, so the result is capped below 100%.
    """
    if days_to_close <= 0:
        return 0.97
    q = days_to_expiry / days_to_close
    return min(0.97, max(0.03, (q - 0.4) / (1.3 - 0.4)))


def scenario_value(deal, contract, probs):
    """Return the three scenarios and the probability-weighted value of the contract.

    deal:     offer, downside, spot, cash (bool), bump (fraction above the offer)
    contract: kind ('call'/'put'), strike, days, rate, vol (normal pre-deal volatility), premium
    probs:    p_close (chance the deal eventually closes), resolve (chance it is decided before
              expiry), p_pending (chance it eventually closes, given it is still pending at expiry)
    """
    T = contract["days"] / 365.0
    r, K, kind = contract["rate"], contract["strike"], contract["kind"]
    O, D, S0 = deal["offer"], deal["downside"], deal["spot"]
    sigma = contract["vol"]

    w1 = probs["p_close"] * probs["resolve"]
    w3 = (1.0 - probs["p_close"]) * probs["resolve"]
    w2 = 1.0 - probs["resolve"]

    s1 = O * (1.0 + deal.get("bump", 0.0))
    s2 = probs["p_pending"] * O + (1.0 - probs["p_pending"]) * D
    s3 = D
    v1_vol = VOL_PINNED_CASH if deal.get("cash", True) else sigma * STOCK_DEAL_VOL_FACTOR

    v1 = black_scholes(s1, K, T, r, v1_vol, kind)
    v2 = black_scholes(s2, K, T, r, VOL_PENDING, kind)
    v3 = black_scholes(s3, K, T, r, sigma, kind)
    fair = w1 * v1 + w2 * v2 + w3 * v3

    plain = black_scholes(S0, K, T, r, sigma, kind)

    # Chance of closing that the market premium implies. The pending scenario is held fixed and
    # the rest of the premium is attributed to close vs break. Value is linear in that chance.
    implied_close = None
    if abs(v1 - v3) > 1e-9 and probs["resolve"] > 1e-9:
        resolved_value = (contract["premium"] - w2 * v2) / probs["resolve"]
        implied_close = min(1.0, max(0.0, (resolved_value - v3) / (v1 - v3)))

    return {
        "scenarios": [
            {"key": "close", "weight": w1, "spot": s1, "value": v1},
            {"key": "pending", "weight": w2, "spot": s2, "value": v2},
            {"key": "break", "weight": w3, "spot": s3, "value": v3},
        ],
        "fair": fair,
        "plain": plain,
        "implied_close": implied_close,
        "edge": (fair - contract["premium"]) / contract["premium"] if contract["premium"] > 0 else None,
    }


def verdict(edge):
    """Plain-language read of how the market premium compares with the model value."""
    if edge is None:
        return "unknown"
    if edge >= 0.20:
        return "buy"
    if edge >= -0.10:
        return "fair"
    return "avoid"


if __name__ == "__main__":
    # Textbook check: S=K=100, 1 year, 5% rate, 20% vol -> call 10.4506, put 5.5735
    c = black_scholes(100, 100, 1, 0.05, 0.2, "call")
    p = black_scholes(100, 100, 1, 0.05, 0.2, "put")
    assert abs(c - 10.4506) < 1e-3, c
    assert abs(p - 5.5735) < 1e-3, p
    # Put-call parity
    assert abs((c - p) - (100 - 100 * math.exp(-0.05))) < 1e-9
    # Weights always sum to 1 and the fair value sits between the scenario extremes
    deal = {"offer": 48.0, "downside": 34.0, "spot": 46.1, "cash": True, "bump": 0.0}
    contract = {"kind": "call", "strike": 45.0, "days": 75, "rate": 0.045, "vol": 0.38, "premium": 2.35}
    probs = {"p_close": 0.95, "resolve": resolved_by_expiry(75, 120), "p_pending": 0.9}
    out = scenario_value(deal, contract, probs)
    assert abs(sum(s["weight"] for s in out["scenarios"]) - 1) < 1e-12
    vals = [s["value"] for s in out["scenarios"]]
    assert min(vals) - 1e-9 <= out["fair"] <= max(vals) + 1e-9
    print("black-scholes OK: call %.4f put %.4f" % (c, p))
    print("example: fair %.3f plain %.3f edge %+.1f%% verdict %s" % (
        out["fair"], out["plain"], 100 * out["edge"], verdict(out["edge"])))
