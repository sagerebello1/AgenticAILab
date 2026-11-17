"""Hypothetical put sensitivity. No network and no change to the pricers."""
import os

import pricing
import put_benchmark
from historical.put_sensitivity import ANCHOR, measure, render


def test_sensitivity_keeps_both_models_on_the_same_contract():
    result = measure()
    anchor = put_benchmark.benchmark(dict(ANCHOR))
    assert anchor["missing"] == []
    assert anchor["market_premium"] is None
    assert result["findings"]
    assert all(item["kind"] != "invalid" for item in result["findings"])
    for row in result["historical"]:
        assert row["black_scholes"] is None
        assert row["scenario_value"] is None
        assert "volatility" in row["missing"]
        assert "strike" in row["missing"]
    spots = [row for row in result["spot"] if row["result"]["otm"] is True]
    prices = {row["result"]["scenario_value"] for row in spots}
    assert len(prices) == 1
    withheld = [row for row in result["spot"] if row["result"]["otm"] is False]
    assert withheld
    assert all(row["result"]["scenario_value"] is None and row["result"]["black_scholes"] is not None for row in withheld)
    levels = {row["result"]["black_scholes"] for row in result["considerations"]}
    assert len(levels) == 1
    report = render(result)
    assert "hypothetical" in report.lower()
    assert "not evidence" in report
    assert "yfinance" not in report
    text = open(os.path.join(os.path.dirname(__file__), "historical", "put_sensitivity.py"), encoding="utf-8").read()
    assert "yfinance" not in text
    assert "query1.finance.yahoo.com" not in text
    assert pricing.VOL_PINNED_CASH == 0.12
    assert "VOL_PINNED_CASH" not in open(put_benchmark.__file__, encoding="utf-8").read()


if __name__ == "__main__":
    test_sensitivity_keeps_both_models_on_the_same_contract()
    print("ok")
