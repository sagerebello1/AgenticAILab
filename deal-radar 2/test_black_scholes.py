"""Black-Scholes checks. No network, no filings, and no production probability."""
import math

import black_scholes


def test_textbook_call_put_and_parity():
    # S = K = 100, one year, 5% rate, 20% volatility, no dividend.
    row = black_scholes.price(100, 100, 1, 0.05, 0.20)
    assert abs(row["d1"] - 0.35) < 1e-12
    assert abs(row["d2"] - 0.15) < 1e-12
    assert abs(row["call"] - 10.450583572185565) < 1e-9
    assert abs(row["put"] - 5.573526022256971) < 1e-9
    parity = 100 - 100 * math.exp(-0.05)
    assert abs((row["call"] - row["put"]) - parity) < 1e-12


def test_greeks_match_finite_differences():
    spot, strike, years, rate, vol = 100.0, 100.0, 1.0, 0.05, 0.20
    row = black_scholes.price(spot, strike, years, rate, vol)
    step = 0.01
    up = black_scholes.price(spot + step, strike, years, rate, vol)["call"]
    down = black_scholes.price(spot - step, strike, years, rate, vol)["call"]
    assert abs((up - down) / (2 * step) - row["delta_call"]) < 1e-4
    delta_up = black_scholes.price(spot + step, strike, years, rate, vol)["delta_call"]
    delta_down = black_scholes.price(spot - step, strike, years, rate, vol)["delta_call"]
    assert abs((delta_up - delta_down) / (2 * step) - row["gamma"]) < 1e-4
    vol_step = 0.0001
    vega = (black_scholes.price(spot, strike, years, rate, vol + vol_step)["call"]
            - black_scholes.price(spot, strike, years, rate, vol - vol_step)["call"]) / (2 * vol_step)
    assert abs(vega - row["vega"]) < 1e-3
    time_step = 1.0 / 365.0
    later = black_scholes.price(spot, strike, years - time_step, rate, vol)["call"]
    earlier = black_scholes.price(spot, strike, years + time_step, rate, vol)["call"]
    theta = (later - earlier) / (2 * time_step)
    assert abs(theta - row["theta_call"]) < 1e-2
    assert row["delta_put"] < 0 < row["delta_call"]
    assert row["gamma"] > 0 and row["vega"] > 0


def test_expiration_and_zero_volatility_are_discounted_bounds():
    expired = black_scholes.price(110, 100, 0, 0.05, 0.20)
    assert expired["call"] == 10 and expired["put"] == 0
    assert expired["d1"] is None
    worthless = black_scholes.price(90, 100, 0, 0.05, 0.20)
    assert worthless["call"] == 0 and worthless["put"] == 10
    pinned = black_scholes.price(100, 100, 1, 0.05, 0)
    assert abs(pinned["call"] - (100 - 100 * math.exp(-0.05))) < 1e-12
    assert pinned["put"] == 0
    assert black_scholes.price(-1, 100, 1, 0.05, 0.2) is None
    assert black_scholes.price(100, 100, 1, 0.05, -0.2) is None


def test_implied_volatility_returns_the_input_and_rejects_an_impossible_price():
    theoretical = black_scholes.price(100, 100, 1, 0.05, 0.20)["call"]
    found = black_scholes.implied_volatility(theoretical, 100, 100, 1, 0.05, "call")
    assert found["converged"] is True
    assert abs(found["volatility"] - 0.20) < 1e-6
    below = black_scholes.implied_volatility(0.01, 100, 100, 1, 0.05, "call")
    assert below["converged"] is False and below["volatility"] is None
    assert black_scholes.implied_volatility(None, 100, 100, 1, 0.05, "call") is None


def _deal(**overrides):
    assumptions = {
        "spot": 50, "strike": 50, "rate": 0.05, "kind": "call",
        "standalone_volatility": 0.30, "deal_volatility": 0.15,
        "acquisition_probability": 0.4, "failure_probability": 0.25,
        "consideration": "cash", "acquisition_price": 60, "downside": 40,
        "days_to_expiration": 365, "days_to_close": 100, "days_to_announcement": 30,
        "dividend": 0,
    }
    assumptions.update(overrides)
    return assumptions


def test_acquisition_weight_uses_the_supplied_probability_only():
    base = _deal()
    valued = black_scholes.acquisition_option_value(base)
    completed = black_scholes.price(60, 50, 1, 0.05, 0.15)["call"]
    broken = black_scholes.price(40, 50, 1, 0.05, 0.30)["call"]
    no_deal = black_scholes.price(50, 50, 1, 0.05, 0.30)["call"]
    deal = 0.75 * completed + 0.25 * broken
    assert abs(valued["expected"] - (0.4 * deal + 0.6 * no_deal)) < 1e-9
    certain = black_scholes.acquisition_option_value(_deal(acquisition_probability=0, failure_probability=0))
    assert abs(certain["expected"] - no_deal) < 1e-12
    absent = black_scholes.acquisition_option_value(_deal(acquisition_probability=None))
    assert absent["expected"] is None
    stock = black_scholes.acquisition_option_value(_deal(
        consideration="stock", exchange_ratio=0.5, acquirer_price=120, failure_probability=0))
    assert abs(stock["acquisition_level"] - 60) < 1e-12


def test_expiration_does_not_take_a_later_deal_price():
    early = black_scholes.acquisition_option_value(_deal(days_to_expiration=20, days_to_announcement=30))
    no_deal = black_scholes.price(50, 50, 20 / 365.0, 0.05, 0.30)["call"]
    assert early["probability_applied"] is False
    assert abs(early["expected"] - no_deal) < 1e-12
    late_close = black_scholes.acquisition_option_value(_deal(days_to_expiration=50, days_to_close=100, days_to_announcement=10))
    assert late_close["expected"] is None
    leaked = black_scholes.acquisition_option_value(_deal(known_on="2021-03-01", as_of="2021-02-01"))
    assert leaked["expected"] is None and leaked["reason"].startswith("An assumption is dated")


def test_comparison_needs_a_market_price_and_a_cost():
    bare = black_scholes.compare_values(_deal())
    assert bare["market_price"] is None and bare["expected_return"] is None
    assert bare["black_scholes"] is not None and bare["acquisition_value"] is not None
    full = black_scholes.compare_values(_deal(
        market_price=8, transaction_cost_per_share=0.05, probability_low=0.2, probability_high=0.6))
    entry = 8.05
    assert abs(full["expected_return"] - (full["acquisition_value"] - entry) / entry) < 1e-12
    assert full["uncertainty_low"] < full["acquisition_value"] < full["uncertainty_high"]
    assert full["downside_return"] < full["expected_return"]


def test_module_does_not_read_the_production_probability():
    text = open(black_scholes.__file__, encoding="utf-8").read()
    assert "import quote" not in text
    assert "close_probability" not in text
    assert "estimate_probabilities" not in text


if __name__ == "__main__":
    test_textbook_call_put_and_parity()
    test_greeks_match_finite_differences()
    test_expiration_and_zero_volatility_are_discounted_bounds()
    test_implied_volatility_returns_the_input_and_rejects_an_impossible_price()
    test_acquisition_weight_uses_the_supplied_probability_only()
    test_expiration_does_not_take_a_later_deal_price()
    test_comparison_needs_a_market_price_and_a_cost()
    test_module_does_not_read_the_production_probability()
    print("ok")
