"""OTM put benchmark. No network, and no change to the production pricers."""
import math

import black_scholes
import pricing
import put_benchmark
import quote


def _base(**over):
    row = {
        "spot": 50.0,
        "strike": 40.0,
        "days": 90,
        "rate": 0.045,
        "volatility": 0.35,
        "downside": 32.0,
        "days_to_close": 120,
        "consideration": "cash",
        "acquisition_price": 60.0,
        "p_close": 0.90,
        "p_pending": 0.84,
        "market_premium": 1.25,
    }
    row.update(over)
    return row


def _years(days):
    return days / 365.0


def test_standard_otm_put():
    row = put_benchmark.benchmark(_base())
    years = _years(90)
    plain = black_scholes.price(50, 40, years, 0.045, 0.35)["put"]
    direct = pricing.scenario_value(
        {"offer": 60.0, "downside": 32.0, "spot": 50.0, "cash": True},
        {"kind": "put", "strike": 40.0, "days": 90, "rate": 0.045, "vol": 0.35, "premium": 1.25},
        {"p_close": 0.90, "resolve": pricing.resolved_by_expiry(90, 120), "p_pending": 0.84},
    )
    assert row["otm"] is True
    assert abs(row["moneyness"] - 0.8) < 1e-12
    assert row["missing"] == []
    assert row["reason"] is None
    assert abs(row["black_scholes"] - plain) < 1e-12
    assert abs(row["black_scholes"] - pricing.black_scholes(50, 40, years, 0.045, 0.35, "put")) < 1e-9
    assert abs(row["scenario_value"] - direct["fair"]) < 1e-12
    assert row["scenario_value"] != row["black_scholes"]
    assert abs(row["difference"] - (direct["fair"] - plain)) < 1e-12
    assert abs(row["pricing_error_black_scholes"] - (plain - 1.25)) < 1e-12
    assert abs(row["pricing_error_scenario"] - (direct["fair"] - 1.25)) < 1e-12
    assert abs(sum(item["weight"] for item in row["scenarios"]) - 1) < 1e-12


def test_deep_otm_put():
    standard = put_benchmark.benchmark(_base())
    deep = put_benchmark.benchmark(_base(strike=25))
    assert deep["otm"] is True
    assert deep["moneyness"] < 0.6
    assert 0 < deep["black_scholes"] < standard["black_scholes"]
    assert 0 < deep["scenario_value"] < standard["scenario_value"]
    assert deep["missing"] == []


def test_cash_acquisition():
    row = put_benchmark.benchmark(_base())
    years = _years(90)
    close = row["scenarios"][0]
    pinned = black_scholes.price(60, 40, years, 0.045, pricing.VOL_PINNED_CASH)["put"]
    assert row["consideration"] == "cash"
    assert row["acquisition_level"] == 60
    assert close["key"] == "close" and close["spot"] == 60
    assert abs(close["value"] - pinned) < 1e-9
    assert abs(close["value"] - pricing.black_scholes(60, 40, years, 0.045, pricing.VOL_PINNED_CASH, "put")) < 1e-12
    assert pricing.VOL_PINNED_CASH == 0.12


def test_stock_acquisition():
    row = put_benchmark.benchmark(_base(
        consideration="stock",
        exchange_ratio=0.5,
        acquirer_price=80.0,
    ))
    years = _years(90)
    stock_vol = 0.35 * pricing.STOCK_DEAL_VOL_FACTOR
    close = row["scenarios"][0]
    assert row["acquisition_level"] == 40
    assert close["spot"] == 40
    assert abs(close["value"] - pricing.black_scholes(40, 40, years, 0.045, stock_vol, "put")) < 1e-12
    cash_pinned = pricing.black_scholes(40, 40, years, 0.045, pricing.VOL_PINNED_CASH, "put")
    assert abs(close["value"] - cash_pinned) > 1e-6
    assert pricing.STOCK_DEAL_VOL_FACTOR == 0.9


def test_mixed_consideration():
    row = put_benchmark.benchmark(_base(
        consideration="mixed",
        cash_amount=15.0,
        exchange_ratio=0.25,
        acquirer_price=100.0,
    ))
    years = _years(90)
    mixed_vol = 0.35 * pricing.STOCK_DEAL_VOL_FACTOR
    close = row["scenarios"][0]
    level, gap = black_scholes._level({
        "consideration": "mixed",
        "cash_amount": 15.0,
        "exchange_ratio": 0.25,
        "acquirer_price": 100.0,
    })
    assert gap is None and level == 40
    assert row["acquisition_level"] == 40
    assert abs(close["value"] - pricing.black_scholes(40, 40, years, 0.045, mixed_vol, "put")) < 1e-12
    pinned = pricing.black_scholes(40, 40, years, 0.045, pricing.VOL_PINNED_CASH, "put")
    assert abs(close["value"] - pinned) > 1e-6


def test_expiration_before_the_expected_close():
    row = put_benchmark.benchmark(_base(days=30, days_to_close=180))
    resolve = pricing.resolved_by_expiry(30, 180)
    weights = {item["key"]: item["weight"] for item in row["scenarios"]}
    assert row["expires_before_close"] is True
    assert abs(row["resolve"] - resolve) < 1e-12
    assert abs(resolve - 0.03) < 1e-12
    assert abs(weights["pending"] - (1.0 - resolve)) < 1e-12
    assert weights["pending"] > weights["close"] + weights["break"]
    assert row["scenario_value"] is not None
    refused = black_scholes.acquisition_option_value({
        "spot": 50, "strike": 40, "rate": 0.045, "kind": "put",
        "standalone_volatility": 0.35, "deal_volatility": pricing.VOL_PINNED_CASH,
        "acquisition_probability": 0.90, "failure_probability": 0.10,
        "consideration": "cash", "acquisition_price": 60, "downside": 32,
        "days_to_expiration": 30, "days_to_close": 180,
    })
    assert refused["expected"] is None


def test_missing_inputs_stay_missing():
    no_offer = put_benchmark.benchmark(_base(acquisition_price=None))
    assert no_offer["missing"] == ["offer"]
    assert no_offer["scenario_value"] is None
    assert no_offer["acquisition_level"] is None
    assert no_offer["black_scholes"] is not None

    no_downside = put_benchmark.benchmark(_base(downside=None))
    assert no_downside["missing"] == ["downside"]
    assert no_downside["scenario_value"] is None
    assert no_downside["black_scholes"] is not None

    no_ratio = put_benchmark.benchmark(_base(
        consideration="stock", exchange_ratio=None, acquirer_price=80.0,
    ))
    assert no_ratio["missing"] == ["exchange_ratio"]
    assert no_ratio["scenario_value"] is None
    assert no_ratio["acquisition_level"] is None

    no_premium = put_benchmark.benchmark(_base(market_premium=None))
    assert no_premium["missing"] == []
    assert no_premium["black_scholes"] is not None
    assert no_premium["scenario_value"] is not None
    assert no_premium["market_premium"] is None
    assert no_premium["pricing_error_black_scholes"] is None
    assert no_premium["pricing_error_scenario"] is None

    no_probability = put_benchmark.benchmark(_base(p_close=None))
    assert no_probability["missing"] == ["p_close"]
    assert no_probability["scenario_value"] is None
    assert no_probability["p_close"] is None


def test_existing_pricing_behavior_is_unchanged():
    assert pricing.VOL_PINNED_CASH == 0.12
    assert pricing.VOL_PENDING == 0.18
    assert pricing.STOCK_DEAL_VOL_FACTOR == 0.9
    call = pricing.black_scholes(100, 100, 1, 0.05, 0.2, "call")
    put = pricing.black_scholes(100, 100, 1, 0.05, 0.2, "put")
    assert abs(call - 10.4506) < 1e-3
    assert abs(put - 5.5735) < 1e-3
    assert abs((call - put) - (100 - 100 * math.exp(-0.05))) < 1e-9
    textbook = black_scholes.price(100, 100, 1, 0.05, 0.20)
    assert abs(textbook["put"] - 5.573526022256971) < 1e-9
    assert abs(quote.close_probability({})["close"] - quote.BASE_P) < 1e-12
    deal = {"offer": 48.0, "downside": 34.0, "spot": 46.1, "cash": True, "bump": 0.0}
    contract = {"kind": "call", "strike": 45.0, "days": 75, "rate": 0.045, "vol": 0.38, "premium": 2.35}
    probs = {"p_close": 0.95, "resolve": pricing.resolved_by_expiry(75, 120), "p_pending": 0.9}
    out = pricing.scenario_value(deal, contract, probs)
    assert abs(sum(item["weight"] for item in out["scenarios"]) - 1) < 1e-12
    values = [item["value"] for item in out["scenarios"]]
    assert min(values) - 1e-9 <= out["fair"] <= max(values) + 1e-9

    flags = {"hsr": True, "consideration": "stock"}
    flagged = put_benchmark.benchmark(_base(p_close=None, flags=flags, consideration="stock",
                                            exchange_ratio=0.5, acquirer_price=80.0))
    assert abs(flagged["p_close"] - quote.close_probability(flags)["close"]) < 1e-12
    assert abs(flagged["scenarios"][0]["weight"] - flagged["p_close"] * flagged["resolve"]) < 1e-12

    text = open(put_benchmark.__file__, encoding="utf-8").read()
    assert "VOL_PINNED_CASH" not in text
    assert "BASE_P" not in text
    assert "0.90" not in text
    assert "0.93" not in text


if __name__ == "__main__":
    test_standard_otm_put()
    test_deep_otm_put()
    test_cash_acquisition()
    test_stock_acquisition()
    test_mixed_consideration()
    test_expiration_before_the_expected_close()
    test_missing_inputs_stay_missing()
    test_existing_pricing_behavior_is_unchanged()
    print("ok")
