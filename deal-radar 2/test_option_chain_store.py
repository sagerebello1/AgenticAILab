"""Options-chain storage. No network, no yfinance, and no pricing changes."""
import os
import sqlite3
import tempfile

from historical.option_chain_store import init, insert_quote, insert_run
from historical.store import init as init_prices


def _db():
    handle = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    handle.close()
    conn = sqlite3.connect(handle.name)
    conn.row_factory = sqlite3.Row
    init(conn)
    return handle.name, conn


def _quote(**over):
    row = {
        "contract_symbol": "ACME210618P00040000",
        "ticker": "ACME",
        "kind": "put",
        "strike": 40.0,
        "expiration": "2021-06-18",
        "bid": 1.2,
        "ask": 1.4,
        "last_price": 1.3,
        "last_trade_at": "2021-06-01T14:30:00Z",
        "volume": 10,
        "open_interest": 80,
        "implied_volatility": 0.35,
        "underlying_price": 50.0,
        "underlying_quote_at": "2021-06-01T14:30:02Z",
        "collected_at": "2021-06-01T15:00:00Z",
        "source": "fixture",
    }
    row.update(over)
    return row


def test_same_last_trade_and_a_later_collection_keeps_both_quotes():
    path, conn = _db()
    try:
        trade = "2021-06-01T14:30:00Z"
        first = insert_quote(conn, _quote(bid=1.2, ask=1.4, last_trade_at=trade))
        second = insert_quote(conn, _quote(
            bid=0.9, ask=1.1, last_trade_at=trade, collected_at="2021-06-01T18:05:00Z"))
        assert first["inserted"] and second["inserted"]
        assert first["id"] != second["id"]
        stored = conn.execute(
            "SELECT bid, ask, last_trade_at, collected_at FROM option_chain_quotes ORDER BY id").fetchall()
        assert [(row["bid"], row["ask"], row["collected_at"]) for row in stored] == [
            (1.2, 1.4, "2021-06-01T15:00:00Z"),
            (0.9, 1.1, "2021-06-01T18:05:00Z"),
        ]
        assert stored[0]["last_trade_at"] == trade and stored[1]["last_trade_at"] == trade
    finally:
        conn.close()
        os.remove(path)


def test_repeating_the_same_collection_does_not_overwrite():
    path, conn = _db()
    try:
        first = insert_quote(conn, _quote(bid=1.2, ask=1.4))
        again = insert_quote(conn, _quote(bid=9.0, ask=9.5, last_trade_at="2021-06-01T19:00:00Z"))
        assert again["inserted"] is False and again["duplicate"] is True
        assert again["id"] == first["id"]
        stored = conn.execute(
            "SELECT bid, ask, last_trade_at, collected_at FROM option_chain_quotes").fetchall()
        assert len(stored) == 1
        assert stored[0]["bid"] == 1.2 and stored[0]["ask"] == 1.4
        assert stored[0]["last_trade_at"] == "2021-06-01T14:30:00Z"
        assert stored[0]["collected_at"] == "2021-06-01T15:00:00Z"
    finally:
        conn.close()
        os.remove(path)


def test_missing_last_trade_time_still_keeps_each_collection():
    path, conn = _db()
    try:
        first = insert_quote(conn, _quote(last_trade_at=None, bid=1.2, ask=1.4))
        later = insert_quote(conn, _quote(
            last_trade_at=None, bid=0.7, ask=0.9, collected_at="2021-06-01T16:00:00Z"))
        assert first["inserted"] and later["inserted"]
        rows = conn.execute(
            "SELECT bid, ask, last_trade_at, collected_at FROM option_chain_quotes ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["last_trade_at"] is None and rows[1]["last_trade_at"] is None
        assert rows[0]["bid"] == 1.2 and rows[1]["bid"] == 0.7
        assert rows[0]["collected_at"] != rows[1]["collected_at"]
    finally:
        conn.close()
        os.remove(path)


def test_same_contract_with_two_expirations_is_kept():
    path, conn = _db()
    try:
        june = insert_quote(conn, _quote(expiration="2021-06-18"))
        july = insert_quote(conn, _quote(expiration="2021-07-16", bid=0.4, ask=0.6))
        assert june["inserted"] and july["inserted"]
        rows = conn.execute(
            "SELECT expiration, bid FROM option_chain_quotes ORDER BY expiration").fetchall()
        assert [(row["expiration"], row["bid"]) for row in rows] == [
            ("2021-06-18", 1.2),
            ("2021-07-16", 0.4),
        ]
    finally:
        conn.close()
        os.remove(path)


def test_two_sources_can_observe_the_same_contract():
    path, conn = _db()
    try:
        first = insert_quote(conn, _quote(source="fixture", bid=1.2, ask=1.4))
        other = insert_quote(conn, _quote(source="other-feed", bid=1.0, ask=1.3))
        assert first["inserted"] and other["inserted"]
        rows = conn.execute(
            "SELECT source, bid, ask FROM option_chain_quotes ORDER BY source").fetchall()
        assert [(row["source"], row["bid"], row["ask"]) for row in rows] == [
            ("fixture", 1.2, 1.4),
            ("other-feed", 1.0, 1.3),
        ]
    finally:
        conn.close()
        os.remove(path)


def test_a_zero_bid_is_not_stored_as_a_missing_bid():
    path, conn = _db()
    try:
        insert_quote(conn, _quote(bid=None, ask=None))
        insert_quote(conn, _quote(bid=0.0, ask=0.05, collected_at="2021-06-01T16:00:00Z"))
        rows = conn.execute(
            "SELECT bid, ask, collected_at FROM option_chain_quotes ORDER BY collected_at").fetchall()
        assert rows[0]["bid"] is None and rows[0]["ask"] is None
        assert rows[1]["bid"] == 0.0 and rows[1]["ask"] == 0.05
    finally:
        conn.close()
        os.remove(path)


def test_failed_runs_are_kept_and_do_not_write_quotes():
    path, conn = _db()
    try:
        failed = insert_run(
            conn, "GONE", "2021-06-01T15:00:00Z", "fixture", "failed",
            http_status=401, reason="Options endpoint refused the request.")
        repeat = insert_run(
            conn, "GONE", "2021-06-01T15:00:00Z", "fixture", "failed",
            http_status=401, reason="Options endpoint refused the request.")
        later = insert_run(
            conn, "GONE", "2021-06-01T16:00:00Z", "fixture", "unavailable",
            reason="No chain was returned.")
        assert failed["inserted"] and later["inserted"]
        assert repeat["duplicate"] is True and repeat["id"] == failed["id"]
        assert conn.execute("SELECT COUNT(*) AS n FROM option_chain_quotes").fetchone()["n"] == 0
        statuses = [row["status"] for row in conn.execute(
            "SELECT status FROM option_chain_runs ORDER BY id")]
        assert statuses == ["failed", "unavailable"]
        assert conn.execute("SELECT http_status FROM option_chain_runs WHERE id=?", (failed["id"],)).fetchone()["http_status"] == 401
    finally:
        conn.close()
        os.remove(path)


def test_several_tickers_and_expirations_stay_separate():
    path, conn = _db()
    try:
        insert_quote(conn, _quote())
        insert_quote(conn, _quote(
            contract_symbol="ACME210716P00040000", expiration="2021-07-16",
            last_trade_at="2021-06-01T14:30:00Z"))
        insert_quote(conn, _quote(
            contract_symbol="BETA210618C00055000", ticker="BETA", kind="call",
            strike=55.0, expiration="2021-06-18", last_trade_at="2021-06-01T14:30:00Z"))
        rows = conn.execute(
            "SELECT ticker, kind, expiration FROM option_chain_quotes ORDER BY contract_symbol").fetchall()
        assert [(row["ticker"], row["kind"], row["expiration"]) for row in rows] == [
            ("ACME", "put", "2021-06-18"),
            ("ACME", "put", "2021-07-16"),
            ("BETA", "call", "2021-06-18"),
        ]
    finally:
        conn.close()
        os.remove(path)


def test_option_tables_are_not_the_stock_price_table():
    path, conn = _db()
    try:
        init_prices(conn)
        names = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "option_chain_quotes" in names and "option_chain_runs" in names
        assert "historical_stock_prices" in names
        quote_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='option_chain_quotes'").fetchone()["sql"]
        price_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name='historical_stock_prices'").fetchone()["sql"]
        conn.execute(
            """CREATE UNIQUE INDEX ux_option_quote_trade
               ON option_chain_quotes(source, contract_symbol, last_trade_at)""")
        init(conn)
        indexes = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        assert "contract_symbol" not in price_sql
        assert "bar_date" not in quote_sql
        assert "ux_option_quote_trade" not in indexes
        assert "ux_option_quote_observation" in indexes
        text = open(os.path.join(os.path.dirname(__file__), "historical", "option_chain_store.py"), encoding="utf-8").read()
        assert "yfinance" not in text
        assert "query1.finance.yahoo.com" not in text
        assert "query2.finance.yahoo.com" not in text
    finally:
        conn.close()
        os.remove(path)


if __name__ == "__main__":
    test_same_last_trade_and_a_later_collection_keeps_both_quotes()
    test_repeating_the_same_collection_does_not_overwrite()
    test_missing_last_trade_time_still_keeps_each_collection()
    test_same_contract_with_two_expirations_is_kept()
    test_two_sources_can_observe_the_same_contract()
    test_a_zero_bid_is_not_stored_as_a_missing_bid()
    test_failed_runs_are_kept_and_do_not_write_quotes()
    test_several_tickers_and_expirations_stay_separate()
    test_option_tables_are_not_the_stock_price_table()
    print("ok")
