"""Dataset rules. These checks do not train a model and do not call the network."""
import os
from datetime import date, timedelta

from historical.facts import select_fact
from historical.labels import control_label, label_set
from historical.outcomes import outcome_from_text
from historical.prices import last_bar_on_or_before, listing_decision, trading_offset
from historical.providers import SourceError, financial_modeling_prep_bars, polygon_bars, stooq_status
from historical.report import judge
from historical.store import connect, init, insert_news, mark_duplicates
from historical.text import cash_offer, classify_role, count_as_target, exchange_ratio, read_filing

ROOT = os.path.dirname(os.path.abspath(__file__))


def filing(path):
    with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as handle:
        return handle.read()


def test_known_filings_keep_their_roles():
    cases = (
        ("data/preannouncement_prototype/filings/0001628280-26-060181.txt", "GoPro, Inc.", "target"),
        ("data/preannouncement_prototype/filings/0000950103-26-013780.txt", "ACV Auctions Inc.", "target"),
        ("data/preannouncement_prototype/filings/0001140361-26-035986.txt", "Centerspace", "target"),
        ("data/preannouncement_prototype/filings/0001140361-26-037107.txt", "Mistras Group, Inc.", "target"),
        ("data/closing_validation/announcements/0001140361-23-028228.txt", "CIRCOR International, Inc.", "target"),
        ("data/closing_validation/announcements/0001193125-23-169553.txt", "DICE Therapeutics, Inc.", "target"),
        ("data/closing_validation/announcements/0001193125-23-164839.txt", "Nasdaq, Inc.", "buyer"),
    )
    for path, filer, expected in cases:
        role, reason = classify_role(filing(path), filer)
        assert role == expected, (path, role, reason)
    assert count_as_target("target", "Blue Ocean Acquisition Corp") == "spac_vehicle"
    assert count_as_target("target", "CIRCOR International, Inc.") == "target"


def test_dividend_cap_is_not_an_offer_and_a_cash_tender_is():
    csr = filing("data/preannouncement_prototype/filings/0001140361-26-035986.txt")
    acva = filing("data/preannouncement_prototype/filings/0000950103-26-013780.txt")
    dice = filing("data/closing_validation/announcements/0001193125-23-169553.txt")
    assert cash_offer(csr)[0] is None
    assert exchange_ratio(csr) == 3.8
    assert cash_offer(acva)[0] == 10.5
    assert cash_offer(dice)[0] == 48.0
    parsed = read_filing(csr, "Centerspace")
    assert parsed["consideration"] == "stock"
    assert parsed["offer"] is None


def test_completion_language_ignores_the_announcement_tense():
    assert outcome_from_text("The merger was consummated on October 18, 2023.")[0] == "closed"
    assert outcome_from_text("The Merger Agreement was terminated on July 1, 2023.")[0] == "terminated"
    assert outcome_from_text("Upon the consummation of the merger, each share will be cancelled.")[0] == "unresolved"
    later = "On October 18, 2023, Merger Sub merged with and into the Company on the terms and conditions set forth in the Merger Agreement."
    assert outcome_from_text(later)[0] == "closed"
    assert outcome_from_text("Merger Sub will merge with and into the Company.")[0] == "unresolved"


def test_horizons_are_not_copies_and_unfinished_windows_stay_blank():
    announcement = date(2024, 6, 1)
    today = date(2024, 12, 31)
    labels = label_set(announcement - timedelta(days=90), announcement, today)
    assert labels == {30: 0, 90: 1, 180: 1}
    assert label_set(date(2026, 11, 1), None, date(2026, 11, 9))[180] is None
    assert control_label(date(2024, 1, 1), [date(2024, 4, 1)], 180, date(2026, 11, 9)) is None
    assert control_label(date(2024, 1, 1), [], 180, date(2026, 11, 9)) == 0


def test_snapshot_price_cannot_see_the_announcement():
    announcement = date(2024, 6, 3)
    bars = [
        {"date": date(2024, 5, 31), "close": 10.0},
        {"date": announcement, "close": 14.0},
        {"date": date(2024, 6, 4), "close": 13.0},
    ]
    snapshot = date(2024, 5, 31)
    chosen = last_bar_on_or_before(bars, snapshot)
    assert chosen["date"] < announcement
    assert chosen["close"] == 10.0
    assert trading_offset(bars, announcement, -1)["close"] == 10.0
    assert trading_offset(bars, announcement, 0)["close"] == 14.0
    assert trading_offset(bars, announcement, 1)["close"] == 13.0


def test_a_reused_ticker_is_not_the_old_company():
    meta = {"symbol": "CIR", "firstTradeDate": 1783431000, "longName": "Corgi CRCL 2x Daily ETF"}
    assert listing_decision(meta, date(2023, 6, 5), "CIR") == "current_listing_starts_after_historical_date"


def test_future_financials_are_dropped():
    rows = [
        {"filed": "2024-03-01", "form": "10-K", "val": 10, "end": "2023-12-31"},
        {"filed": "2025-03-01", "form": "10-K", "val": 99, "end": "2024-12-31"},
    ]
    assert select_fact(rows, "2024-06-01")["value"] == 10


def test_missing_provider_keys_do_not_return_prices():
    os.environ.pop("FMP_API_KEY", None)
    os.environ.pop("POLYGON_API_KEY", None)
    for func in (financial_modeling_prep_bars, polygon_bars):
        try:
            func("AAPL", date(2024, 1, 2), date(2024, 1, 5))
        except SourceError:
            continue
        raise AssertionError("a missing key returned bars")
    assert stooq_status("<html><body>This site requires JavaScript to verify your browser.</body></html>") == "blocked"


def test_duplicates_are_one_transaction_and_news_needs_a_date():
    import tempfile
    path = os.path.join(tempfile.mkdtemp(), "ma.sqlite")
    conn = connect(path)
    init(conn)
    for adsh, day in (("a", "2023-06-01"), ("b", "2023-06-04"), ("c", "2023-08-01")):
        conn.execute(
            """INSERT INTO historical_ma_transactions
               (adsh, target_cik, announcement_date, role, is_amendment)
               VALUES (?, 1, ?, 'target', 0)""",
            (adsh, day),
        )
    mark_duplicates(conn)
    rows = {row["adsh"]: row["duplicate_of"] for row in conn.execute("SELECT adsh, duplicate_of FROM historical_ma_transactions")}
    assert rows["b"] == "a"
    assert rows["c"] is None
    competing = conn.execute("SELECT competing_adsh FROM historical_ma_transactions WHERE adsh='a'").fetchone()[0]
    assert competing == "c"
    try:
        insert_news(conn, {"headline": "no date"})
    except ValueError:
        pass
    else:
        raise AssertionError("undated news was stored")
    assert conn.execute("SELECT COUNT(*) FROM historical_news_signals").fetchone()[0] == 0
    conn.close()


def test_small_counts_are_not_ready_for_training():
    judgment = judge({
        "usable_30": 8, "usable_90": 0, "usable_180": 0,
        "positives_30": 4, "positives_90": 0, "positives_180": 0,
        "negatives_30": 4, "negatives_90": 0, "negatives_180": 0,
        "event_deals": 4, "outcome_labeled": 18, "terminated": 2,
        "lookahead_violations": 0, "verified_transactions": 8,
    })
    assert judgment["trained"] is False
    assert judgment["acquisition"] is False
    assert judgment["post_announcement_price"] is False
    assert judgment["deal_completion"] is False


if __name__ == "__main__":
    test_known_filings_keep_their_roles()
    test_dividend_cap_is_not_an_offer_and_a_cash_tender_is()
    test_completion_language_ignores_the_announcement_tense()
    test_horizons_are_not_copies_and_unfinished_windows_stay_blank()
    test_snapshot_price_cannot_see_the_announcement()
    test_a_reused_ticker_is_not_the_old_company()
    test_future_financials_are_dropped()
    test_missing_provider_keys_do_not_return_prices()
    test_duplicates_are_one_transaction_and_news_needs_a_date()
    test_small_counts_are_not_ready_for_training()
    print("ok")
