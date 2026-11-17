"""Historical put coverage. No network and no live pricing changes."""
import os
import sqlite3
import tempfile
from datetime import date, timedelta

from historical.put_backtest import measure, render
from historical.store import connect, init


def _db():
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    handle.close()
    conn = connect(handle.name)
    init(conn)
    return handle.name, conn


def _deal(conn, adsh, ticker, consideration, offer, ratio, announced, closes):
    conn.execute(
        """INSERT INTO historical_ma_transactions
           (adsh, target_ticker, announcement_date, consideration, offer_price, exchange_ratio, role, is_amendment)
           VALUES (?, ?, ?, ?, ?, ?, 'target', 0)""",
        (adsh, ticker, announced, consideration, offer, ratio),
    )
    day = date.fromisoformat(announced)
    for offset, close in closes:
        conn.execute(
            """INSERT INTO historical_stock_prices (ticker, bar_date, close, source)
               VALUES (?, ?, ?, 'yahoo-chart')""",
            (ticker, (day + timedelta(days=offset)).isoformat(), close),
        )
    conn.commit()


def test_cash_put_uses_only_stored_prices():
    path, conn = _db()
    try:
        announced = "2021-06-01"
        closes = [(-3, 50.0)] + [(offset, 40.0) for offset in range(0, 40)]
        _deal(conn, "cash-1", "ACME", "cash", 60.0, None, announced, closes)
        result = measure(conn)
        assert result["coverage"]["verified"] == 1
        assert result["coverage"]["offer_price"] == 1
        assert result["coverage"]["consideration_cash"] == 1
        assert result["scored_count"] == 1
        row = result["scored"][0]
        assert row["spot"] == 50.0
        assert abs(row["strike"] - 40.0) < 1e-12
        assert row["later"] == 40.0
        assert row["payoff"] == 0.0
        assert result["market_pricing_error"] is None
        assert result["model_payoff_error"] is None
        text = render(result)
        assert "not computed" in text
        assert "option premium" in text
    finally:
        conn.close()
        os.remove(path)


def test_missing_offer_later_price_and_stock_terms_are_not_scored():
    path, conn = _db()
    try:
        _deal(conn, "no-offer", "NOOF", "cash", None, None, "2021-06-01",
              [(-2, 20.0)] + [(n, 18.0) for n in range(35)])
        _deal(conn, "no-later", "NOLT", "cash", 25.0, None, "2021-06-01", [(-2, 20.0)])
        _deal(conn, "stock-1", "STOK", "stock", None, 0.5, "2021-07-01",
              [(-2, 30.0)] + [(n, 28.0) for n in range(35)])
        _deal(conn, "blank", "BLNK", None, None, None, "2021-08-01", [])
        result = measure(conn)
        assert result["scored_count"] == 0
        assert result["mean_payoff"] is None
        assert result["coverage"]["exchange_ratio"] == 1
        assert result["missing"]["offer_price"] == 3
        assert result["missing"]["consideration"] == 1
        assert result["missing"]["historical_prices"] == 1
        assert result["market_pricing_error"] is None
        text = render(result)
        assert "Options-market pricing error: not computed" in text
        assert "0.90" not in text
        assert "implied volatility" in text
    finally:
        conn.close()
        os.remove(path)


def test_positive_intrinsic_is_the_later_stock_gap():
    path, conn = _db()
    try:
        closes = [(-1, 100.0)] + [(n, 70.0) for n in range(35)]
        _deal(conn, "drop-1", "DROP", "cash", 110.0, None, "2022-01-03", closes)
        row = measure(conn)["scored"][0]
        assert abs(row["strike"] - 80.0) < 1e-12
        assert abs(row["payoff"] - 10.0) < 1e-12
    finally:
        conn.close()
        os.remove(path)


def test_script_does_not_import_the_live_pricers():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "historical", "put_backtest.py")
    text = open(path, encoding="utf-8").read()
    assert "import pricing" not in text
    assert "import black_scholes" not in text
    assert "import options" not in text
    assert "import quote" not in text


if __name__ == "__main__":
    test_cash_put_uses_only_stored_prices()
    test_missing_offer_later_price_and_stock_terms_are_not_scored()
    test_positive_intrinsic_is_the_later_stock_gap()
    test_script_does_not_import_the_live_pricers()
    print("ok")
