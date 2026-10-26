"""Symbol lookup and index ticker. No network."""
import urllib.error
from datetime import date, datetime, timezone

import edgar
import market
import server
import workflow


def cash_deal(**extra):
    deal = {
        "id": "0001", "ticker": "ACVA", "target": "ACV Auctions Inc.", "filedOn": "2026-10-16",
        "filingStatus": "extracted", "offer": 10.5, "note": "Cash price quoted from a filing",
        "consideration": "cash", "flags": {},
        "catalyst": {"kind": "terms_quoted", "confirmed": True},
        "market": {"spot": 10.5, "downside": 9.0, "asOf": "2026-10-23", "source": "yahoo-chart"},
    }
    deal.update(extra)
    return deal


def _isolated():
    saved = list(server.WORK.book)
    server.WORK.book = []
    return saved


def _restore(saved):
    server.WORK.book = saved


def test_symbol_rules_reject_blank_input_and_keep_the_list_empty():
    saved = _isolated()
    try:
        def boom(symbol):
            raise AssertionError("lookup should not run")
        out = server.lookup_symbol("  ", find_company=boom, search_deals=boom, identity=boom)
        assert out["ok"] is False and out["name"] is None and out["deal"] is None
        assert "AAPL" in out["error"]
        assert server.lookup_symbol("^DJI", find_company=boom, search_deals=boom, identity=boom)["ok"] is False
        assert server.WORK.book == []
    finally:
        _restore(saved)


def test_sec_name_is_used_and_a_second_search_does_not_add_a_row():
    saved = _isolated()
    calls = {"n": 0}

    def find_company(symbol):
        assert symbol == "ACVA"
        return {"ticker": "ACVA", "name": "ACV Auctions Inc.", "cik": 1637873}

    def search_deals(company, today):
        calls["n"] += 1
        return {"status": "added", "deal": cash_deal(), "message": "A filing quotes a cash price and the quote has a stock price and a break price, so it was added. The same buy, sell, and wait rules apply."}

    def identity(symbol):
        raise AssertionError("Yahoo should not name a company that is on the SEC list")

    try:
        first = server.lookup_symbol("acva", today=date(2026, 10, 24), find_company=find_company, search_deals=search_deals, identity=identity)
        assert first["ok"] is True
        assert first["symbol"] == "ACVA" and first["name"] == "ACV Auctions Inc."
        assert first["nameSource"] == "sec-company-tickers"
        assert first["added"] is True and first["eligible"] is True
        assert len(server.WORK.book) == 1
        second = server.lookup_symbol("ACVA", today=date(2026, 10, 24), find_company=find_company, search_deals=search_deals, identity=identity)
        assert second["added"] is False and second["alreadyListed"] is True
        assert calls["n"] == 1 and len(server.WORK.book) == 1
    finally:
        _restore(saved)


def test_a_filing_without_a_cash_quote_is_not_added():
    saved = _isolated()

    def find_company(symbol):
        return {"ticker": "AAPL", "name": "Apple Inc.", "cik": 320193}

    def search_deals(company, today):
        return {"status": "none", "deal": None, "message": "No merger agreement or tender offer for this company in the last 120 days. The company list is unchanged. That is not a close chance of zero."}

    try:
        out = server.lookup_symbol("AAPL", find_company=find_company, search_deals=search_deals, identity=lambda symbol: None)
        assert out["ok"] is True and out["name"] == "Apple Inc."
        assert out["added"] is False and out["deal"] is None
        assert "not a close chance of zero" in out["message"]
        assert server.WORK.book == []
    finally:
        _restore(saved)


def test_unknown_symbol_does_not_invent_a_name():
    saved = _isolated()

    def find_company(symbol):
        return None

    def identity(symbol):
        raise market.MarketError("Yahoo has no listing for %s. No price was substituted." % symbol)

    try:
        out = server.lookup_symbol("ZZZZ", find_company=find_company, search_deals=lambda c, t: None, identity=identity)
        assert out["ok"] is False and out["name"] is None
        assert "no listing" in out["error"]
        assert server.WORK.book == []
    finally:
        _restore(saved)


def test_company_ticker_file_skips_a_nameless_row_and_accepts_a_class_share():
    mapping = edgar.parse_company_tickers({
        "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
        "1": {"cik_str": 1, "ticker": "BLANK", "title": "  "},
        "2": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
    })
    assert edgar.lookup_ticker(mapping, "aapl")["name"] == "Apple Inc."
    assert edgar.lookup_ticker(mapping, "BLANK") is None
    assert edgar.lookup_ticker(mapping, "NOPE") is None
    assert edgar.lookup_ticker(mapping, "BRK.B")["ticker"] == "BRK-B"


def test_price_move_keeps_zero_separate_from_missing():
    same = market.price_move(100, 100)
    assert same["direction"] == "unchanged" and same["change"] == 0 and same["changePct"] == 0
    assert market.price_move(110, 100)["direction"] == "up"
    assert market.price_move(90, 100)["change"] < 0
    assert market.price_move(100, None) is None
    assert market.price_move(None, 100) is None


def test_failed_index_stays_blank_and_a_delayed_move_is_not_realtime():
    missing = server.present_index(
        {"id": "SPX", "name": "S&P 500", "symbol": "^GSPC"}, None,
        "Yahoo chart for ^GSPC timed out after 12 seconds. No price was substituted.")
    assert missing["price"] is None and missing["change"] is None
    assert missing["available"] is False and missing["realtime"] is False
    flat = server.present_index(
        {"id": "DJI", "name": "Dow Jones", "symbol": "^DJI"},
        {"querySymbol": "^DJI", "price": 100.0, "previous": 100.0, "change": 0.0,
         "changePct": 0.0, "direction": "unchanged", "asOf": "2026-10-23"},
        None, today=date(2026, 10, 24))
    assert flat["available"] is True and flat["change"] == 0
    assert flat["direction"] == "unchanged" and flat["freshness"] == "delayed"
    assert flat["realtime"] is False and flat["freshness"] != "realtime"


def test_index_board_caches_rows_and_does_not_fill_a_failed_index():
    server._INDEX_CACHE.clear()
    calls = {"n": 0}

    def fetch(symbol):
        calls["n"] += 1
        if symbol == "^IXIC":
            raise market.MarketError("Yahoo chart for ^IXIC timed out after 12 seconds. No price was substituted.")
        return {"querySymbol": symbol, "price": 10.0, "previous": 9.0, "change": 1.0,
                "changePct": 1 / 9, "direction": "up", "asOf": "2026-10-23"}

    try:
        moment = datetime(2026, 10, 24, tzinfo=timezone.utc)
        server.index_board(now=moment, fetch=fetch, today=date(2026, 10, 24))
        board = server.index_board(now=moment, fetch=fetch, today=date(2026, 10, 24))
        assert calls["n"] == 3
        assert board["realtime"] is False and "not a real-time quote" in board["note"]
        by_id = {row["id"]: row for row in board["indices"]}
        assert set(by_id) == {"DJI", "IXIC", "SPX"}
        assert by_id["IXIC"]["price"] is None and by_id["IXIC"]["available"] is False
        assert by_id["DJI"]["price"] == 10 and by_id["DJI"]["freshness"] == "delayed"
        assert by_id["SPX"]["querySymbol"] == "^GSPC"
    finally:
        server._INDEX_CACHE.clear()


def test_yahoo_rate_limit_names_the_chart():
    saved = market.urllib.request.urlopen

    def boom(*args, **kwargs):
        raise urllib.error.HTTPError("https://query1.finance.yahoo.com/v8/finance/chart/AAPL", 429, "Too Many Requests", hdrs=None, fp=None)

    market.urllib.request.urlopen = boom
    try:
        try:
            market.history("AAPL", date(2026, 10, 1), date(2026, 10, 2))
            raise AssertionError("expected a market error")
        except market.MarketError as e:
            assert "rate-limited" in str(e)
            assert "No price was substituted." in str(e)
    finally:
        market.urllib.request.urlopen = saved


def test_page_has_search_and_the_index_ticker_without_an_order_route():
    page = open(server.os.path.join(server.HERE, "static", "app.html"), encoding="utf-8").read()
    source = open(server.__file__, encoding="utf-8").read()
    assert 'id="lookupForm"' in page and 'id="lookupBtn"' in page and "Searching…" in page
    assert "Dow Jones" in page and "NASDAQ Composite" in page and "S&P 500" in page
    assert "prefers-reduced-motion" in page and "animation-play-state:paused" in page
    assert "upsertSearched" in page and "/api/order" not in source
    assert workflow.price_label("2026-10-23", date(2026, 10, 24)) == "delayed"


if __name__ == "__main__":
    test_symbol_rules_reject_blank_input_and_keep_the_list_empty()
    test_sec_name_is_used_and_a_second_search_does_not_add_a_row()
    test_a_filing_without_a_cash_quote_is_not_added()
    test_unknown_symbol_does_not_invent_a_name()
    test_company_ticker_file_skips_a_nameless_row_and_accepts_a_class_share()
    test_price_move_keeps_zero_separate_from_missing()
    test_failed_index_stays_blank_and_a_delayed_move_is_not_realtime()
    test_index_board_caches_rows_and_does_not_fill_a_failed_index()
    test_yahoo_rate_limit_names_the_chart()
    test_page_has_search_and_the_index_ticker_without_an_order_route()
    print("ok")
