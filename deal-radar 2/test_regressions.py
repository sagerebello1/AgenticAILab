"""Counts, timeouts, the discounted value, headline scores, and visible labels."""
import math
import socket
from datetime import date, datetime, timezone

import edgar
import market
import news
import quote
import server
import terms
import workflow
from workflow import Workflow, listed_company, merge_deals


def test_pag_value_discounts_the_offer_before_weighting_the_chance():
    offer, down, chance, days, rate = 212.0, 194.79, 0.91, 162, 0.045
    discounted = offer * math.exp(-rate * days / 365.0)
    expected = chance * discounted + (1.0 - chance) * down
    undiscounted = chance * offer + (1.0 - chance) * down
    out = quote.respond({
        "offer": offer, "spot": offer, "downside": down, "days": days, "p": chance, "rate": rate,
    })
    assert abs(expected - 206.63) < 0.02
    assert abs(out["fairValue"] - expected) < 0.02
    assert out["fairValue"] < undiscounted - 3
    assert out["discountedOffer"] < offer
    assert out["bid"] < out["fairValue"] < out["ask"]
    assert out["action"] == "pass"
    rich = quote.respond({"offer": offer, "spot": 220, "downside": down, "days": days, "p": chance, "rate": rate})
    cheap = quote.respond({"offer": offer, "spot": 180, "downside": down, "days": days, "p": chance, "rate": rate})
    assert rich["action"] == "ask" and cheap["action"] == "bid"


def test_listed_count_matches_the_sidebar_and_ignores_a_duplicate_company():
    ready = {
        "id": "1", "cik": 9, "ticker": "", "filedOn": "2026-10-01", "filingStatus": "extracted",
        "offer": 50.0, "note": "Cash price quoted from a filing",
        "catalyst": {"kind": "terms_quoted"}, "market": {"spot": 40.0, "downside": 30.0},
    }
    newer = dict(ready, id="2", filedOn="2026-10-18", note="Cash price quoted again")
    book, _ = merge_deals([ready], [newer])
    assert len(book) == 1
    missing = dict(ready, id="3", cik=10, ticker="CCO", market={"spot": 2.42, "downside": None})
    desk = Workflow()
    desk.ingest({"mode": "live", "scannedAt": "2026-10-19T00:00:00Z", "deals": book + [missing]})
    status = desk.status()
    assert status["listed"] == 1
    assert status["quotedCash"] == 2
    assert status["activeQuoted"] == status["listed"]
    assert listed_company(missing) is False


def test_one_sec_search_timeout_keeps_the_other_and_does_not_invent_a_price():
    saved = (edgar.search_filings, server.read_filing, market.history, server.EDGAR_UA)
    server.EDGAR_UA = "Deal Radar test example@example.com"

    def search(user_agent, days=30, query='"agreement and plan of merger"', forms="8-K", size=40):
        if forms == "8-K":
            raise edgar.EdgarError("SEC request to efts.sec.gov timed out after 20 seconds. No filing text was substituted.")
        return [{"adsh": "1", "ticker": "PAG", "cik": 1019849, "filer": "Penske", "filedOn": "2026-10-01",
                 "items": ["1.01"], "form": "8-K", "indexUrl": "", "docUrl": None},
                {"adsh": "2", "ticker": "CCO", "cik": 2, "filer": "Clear Channel", "filedOn": "2026-10-01",
                 "items": ["1.01"], "form": "8-K", "indexUrl": "", "docUrl": None}]

    def history(ticker, start, end, timeout=15):
        if ticker == "CCO":
            raise market.MarketError("Yahoo chart for CCO timed out after 15 seconds. No price was substituted.")
        return [(date(2026, 9, 1), 194.79), (date(2026, 10, 19), 212.0)]

    edgar.search_filings = search
    server.read_filing = lambda rec: ("The offer is $212.00 per share.", [], None)
    market.history = history
    try:
        out = server.scan(30, 12)
    finally:
        edgar.search_filings, server.read_filing, market.history, server.EDGAR_UA = saved
    assert out["mode"] == "live"
    assert [d["ticker"] for d in out["deals"]] == ["PAG", "CCO"]
    assert any("8-K" in w and "timed out" in w for w in out["warnings"])
    pag = out["deals"][0]
    cco = out["deals"][1]
    assert pag["offer"] == 212
    assert pag["market"]["spot"] == 212
    assert cco["market"]["spot"] is None
    assert "timed out" in cco["marketError"]
    assert "substituted" in cco["marketError"]


def test_yahoo_timeout_names_the_chart_instead_of_the_raw_socket_error():
    saved = market.urllib.request.urlopen

    def boom(*args, **kwargs):
        raise socket.timeout("The read operation timed out")

    market.urllib.request.urlopen = boom
    try:
        try:
            market.history("PAG", date(2026, 1, 1), date(2026, 1, 2))
            raise AssertionError("expected a market error")
        except market.MarketError as e:
            assert "Yahoo chart for PAG timed out" in str(e)
            assert "The read operation timed out" not in str(e)
    finally:
        market.urllib.request.urlopen = saved


def test_headline_zero_is_scored_and_a_missing_score_is_separate():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    plain = news.score([{"title": "Penske reports earnings", "link": "http://x", "published": now}],
                       names=("Penske Automotive",), now=now)
    assert plain["headlines"][0]["weight"] == 0
    assert plain["headlines"][0]["scored"] is True
    blocked = news.score([{"title": "Regulators sue to block the Penske merger", "link": "", "published": now}],
                         names=("Penske",), now=now)
    assert blocked["headlines"][0]["weight"] < 0
    assert blocked["headlines"][0]["scored"] is True
    page = open(server.os.path.join(server.HERE, "static", "app.html"), encoding="utf-8").read()
    assert "function scoreLabel" in page
    assert "Not scored" in page
    assert "h.weight ? " not in page


def test_visible_labels_are_not_hex_entities_and_filing_text_is_decoded():
    page = open(server.os.path.join(server.HERE, "static", "app.html"), encoding="utf-8").read()
    assert "&#x65;" not in page
    for label in ("Your value", "If the deal dies", "Highest price to buy"):
        assert label in page
    text = terms.to_text("Your valu&#x65; and if the deal di&#x65;s. <b>Highest price to buy</b>")
    assert "&#x" not in text
    assert text == "Your value and if the deal dies. Highest price to buy"
    assert "<" not in terms.to_text("<script>alert(1)</script>Your value")


if __name__ == "__main__":
    test_pag_value_discounts_the_offer_before_weighting_the_chance()
    test_listed_count_matches_the_sidebar_and_ignores_a_duplicate_company()
    test_one_sec_search_timeout_keeps_the_other_and_does_not_invent_a_price()
    test_yahoo_timeout_names_the_chart_instead_of_the_raw_socket_error()
    test_headline_zero_is_scored_and_a_missing_score_is_separate()
    test_visible_labels_are_not_hex_entities_and_filing_text_is_decoded()
    print("ok")
