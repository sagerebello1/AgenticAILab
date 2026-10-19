"""Scheduled book: dedupe, price labels, and quote recalculation. No network."""
import json
import os
from datetime import date, datetime, timezone

import options
import server
import workflow
from workflow import Workflow, merge_deals, price_label, recalculate, stamp_price


def cash_deal(**extra):
    deal = {
        "id": "0001", "ticker": "RGR", "target": "Sturm Ruger", "filedOn": "2026-10-01",
        "filingStatus": "extracted", "offer": 50.0, "note": "Cash price quoted from a filing",
        "consideration": "cash", "flags": {},
        "catalyst": {"kind": "terms_quoted", "confirmed": True},
        "market": {"spot": 40.0, "downside": 30.0, "asOf": "2026-10-19", "source": "yahoo-chart"},
    }
    deal.update(extra)
    return deal


def test_intervals_are_configurable_and_have_a_floor():
    os.environ["DEAL_RADAR_SCAN_SECONDS"] = "30"
    os.environ["DEAL_RADAR_PRICE_SECONDS"] = "nope"
    try:
        assert workflow.seconds("DEAL_RADAR_SCAN_SECONDS", 1800, 120) == 120
        assert workflow.seconds("DEAL_RADAR_PRICE_SECONDS", 300, 60) == 300
        assert workflow.seconds("DEAL_RADAR_MISSING", 1800, 120) == 1800
    finally:
        os.environ.pop("DEAL_RADAR_SCAN_SECONDS", None)
        os.environ.pop("DEAL_RADAR_PRICE_SECONDS", None)


def test_scans_do_not_duplicate_a_ticker_and_a_newer_filing_replaces_the_old_one():
    first, changes = merge_deals([], [cash_deal()])
    assert changes["added"] == ["T:RGR"] and len(first) == 1
    again, changes = merge_deals(first, [cash_deal()])
    assert len(again) == 1 and changes["added"] == [] and changes["updated"] == []
    newer = cash_deal(id="0002", filedOn="2026-10-18", offer=None, filingStatus="terms_need_verification",
                      note="This filing ends a merger agreement.")
    book, changes = merge_deals(again, [newer])
    assert len(book) == 1 and book[0]["id"] == "0002" and book[0]["statusChanged"] is True
    assert book[0]["previousFiling"]["offer"] == 50.0
    older = cash_deal()
    kept, _ = merge_deals(book, [older])
    assert kept[0]["id"] == "0002"
    other, _ = merge_deals(kept, [cash_deal(id="9", ticker="PAG", target="Penske")])
    assert [d["ticker"] for d in other] == ["RGR", "PAG"]


def test_price_is_delayed_or_stale_and_never_real_time():
    assert price_label("2026-10-19", date(2026, 10, 19)) == "delayed"
    assert price_label("2026-10-17", date(2026, 10, 19)) == "delayed"
    assert price_label("2026-10-01", date(2026, 10, 19)) == "stale"
    assert price_label(None, date(2026, 10, 19)) == "unavailable"
    stamped = stamp_price(cash_deal(), datetime(2026, 10, 19, tzinfo=timezone.utc), date(2026, 10, 19))
    assert stamped["price"]["source"] == "yahoo-chart"
    assert stamped["price"]["freshness"] == "delayed"
    assert stamped["price"]["retrievedAt"].startswith("2026-10-19")
    assert "real-time" in stamped["price"]["note"]
    assert stamped["price"]["freshness"] not in ("realtime", "live")
    blank = stamp_price(cash_deal(market={"spot": None}), datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert blank["price"]["freshness"] == "unavailable"
    assert blank["price"]["source"] is None


def test_metrics_recalculate_when_the_stock_price_changes_and_stay_blank_without_inputs():
    deal = recalculate(cash_deal(), date(2026, 10, 19))
    first = deal["metrics"]["quote"]
    assert first["bid"] < first["ask"]
    p_close = first["pClose"]
    deal["market"]["spot"] = 48
    deal = recalculate(deal, date(2026, 10, 19))
    assert deal["metrics"]["quote"]["bid"] != first["bid"]
    assert deal["metrics"]["quote"]["pClose"] == p_close
    missing = recalculate({"offer": None, "market": {"spot": 10, "downside": 8}, "flags": {}})
    assert missing["metrics"]["quote"] is None


def test_a_failed_scan_does_not_insert_sample_deals_and_a_price_error_is_recorded():
    book = Workflow(scan_seconds=1800, price_seconds=300)
    book.ingest({"mode": "error", "reason": "SEC EDGAR did not answer.", "deals": [{"ticker": "MARR", "target": "Marrow"}]})
    assert book.book == []
    assert "Marrow" not in json.dumps(book.payload())
    book.ingest({"mode": "live", "scannedAt": "2026-10-19T12:00:00Z", "deals": [cash_deal()]})
    assert book.status()["activeQuoted"] == 1
    assert book.status()["lastScan"] == "2026-10-19T12:00:00Z"
    assert book.status()["optionsAvailable"] is False

    def boom(ticker):
        raise RuntimeError("chart down")

    book.price_fn = boom
    book.refresh_prices(datetime(2026, 10, 19, tzinfo=timezone.utc))
    assert "chart down" in book.last_price_error
    assert book.book[0]["price"]["freshness"] != "realtime"

    def delayed(ticker):
        return {"spot": 41.25, "asOf": "2026-10-16"}

    book.price_fn = delayed
    book.refresh_prices(datetime(2026, 10, 19, 18, 0, tzinfo=timezone.utc), date(2026, 10, 19))
    assert book.book[0]["market"]["spot"] == 41.25
    assert book.book[0]["market"]["downside"] == 30.0
    assert book.book[0]["price"]["freshness"] == "delayed"
    assert book.book[0]["price"]["source"] == "yahoo-chart"
    assert book.last_price_ok.startswith("2026-10-19")
    assert book._thread is None


def test_options_chain_stays_unavailable_and_no_audited_source_was_added():
    assert options.CHAIN["available"] is False
    assert options.CHAIN["http"] == 401
    assert options.AUDIT and all(row["used"] is False for row in options.AUDIT)
    assert server.WORK._thread is None
    text = open(server.__file__, encoding="utf-8").read()
    assert "cdn.cboe.com" not in text
    assert "/api/order" not in text


if __name__ == "__main__":
    test_intervals_are_configurable_and_have_a_floor()
    test_scans_do_not_duplicate_a_ticker_and_a_newer_filing_replaces_the_old_one()
    test_price_is_delayed_or_stale_and_never_real_time()
    test_metrics_recalculate_when_the_stock_price_changes_and_stay_blank_without_inputs()
    test_a_failed_scan_does_not_insert_sample_deals_and_a_price_error_is_recorded()
    test_options_chain_stays_unavailable_and_no_audited_source_was_added()
    print("ok")
