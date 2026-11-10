"""Bulk GKG rules. These checks do not download files and do not fit a model."""
from datetime import date, datetime, timedelta, timezone

from historical.gdelt_bulk import (
    acquisition_themes,
    backoff_seconds,
    day_complete,
    gkg_files_for_day,
    join_day,
    keep_earliest,
    match_terms,
    matching_org,
    parse_gkg_line,
    parse_index_line,
    rolling_change,
    should_retry,
    theme_codes,
)


def stamp(day, hour=12):
    return datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=timezone.utc)


def test_index_keeps_one_gkg_day_and_rejects_a_later_lookalike():
    rows = [
        parse_index_line("10 aaa http://data.gdeltproject.org/gdeltv2/20210203000000.gkg.csv.zip"),
        parse_index_line("11 bbb http://data.gdeltproject.org/gdeltv2/20210203001500.export.CSV.zip"),
        parse_index_line("12 ccc http://data.gdeltproject.org/gdeltv2/20220210203000.gkg.csv.zip"),
    ]
    chosen = gkg_files_for_day(rows, date(2021, 2, 3))
    assert [row["name"] for row in chosen] == ["20210203000000.gkg.csv.zip"]
    assert chosen[0]["md5"] == "aaa"


def test_rate_limit_is_not_retried_and_a_server_error_backs_off():
    assert should_retry(429, 0) is False
    assert should_retry(503, 0) is True
    assert should_retry(503, 2) is False
    assert should_retry(None, 0) is True
    assert backoff_seconds(1, 0.25) == 2.25


def test_publication_time_is_not_taken_from_the_processing_stamp_or_mentioned_dates():
    line = "\t".join([
        "id", "20210203000000", "1", "example.com", "https://example.com/story",
        "", "", "ECON_MERGER", "ECON_MERGER,10", "", "", "", "",
        "Acme Corp", "Acme Corp,4", "-1.5,2,3,4,5,0,100", "1#0#0#1999#1",
    ])
    row = parse_gkg_line(line)
    assert row["published_at"] is None
    assert row["observed_at"] == stamp(date(2021, 2, 3), 0)
    assert row["tone"] == -1.5
    assert row["acquisition_themes"] == ["ECON_MERGER"]
    assert "EMERGENCY" not in acquisition_themes(theme_codes("EMERGENCY", ""))


def test_one_article_matches_a_company_once_and_a_later_copy_is_dropped():
    found, terms = match_terms("PayPal Holdings, Inc.", "PYPL", 1)
    assert found["status"] == "queryable"
    org, kind, term = matching_org(["PayPal", "PayPal Holdings"], terms)
    assert org == "PayPal" and kind == "name"
    assert matching_org(["Wheeler"], match_terms("Wheeler Real Estate Investment Trust, Inc.", "WHLR", 2)[1])[0] is None
    otis_terms = match_terms("Otis Worldwide Corp", "OTIS", 3)[1]
    assert matching_org(["Otis Technology"], otis_terms)[0] is None
    assert matching_org(["Otis Worldwide Corporation"], otis_terms)[0] == "Otis Worldwide Corporation"
    early = {"url": "https://example.com/a", "observed_at": stamp(date(2021, 2, 3), 0)}
    late = {"url": "https://example.com/a", "observed_at": stamp(date(2021, 2, 3), 6)}
    kept, dropped = keep_earliest([late, early])
    assert dropped == 1
    assert kept[0]["observed_at"] == early["observed_at"]


def test_news_after_the_cutoff_is_not_zero_and_a_gap_is_not_zero():
    day = date(2021, 2, 3)
    mentions = [{
        "observed_at": stamp(day, 0),
        "source": "example.com",
        "tone": -2,
        "acquisition_themes": ["MERGER"],
    }]
    blocked = join_day(mentions, date(2021, 2, 2), day, True)
    assert blocked["mentions"] is None and blocked["reason"] == "archive_after_cutoff"
    missing = join_day([], day, day, False)
    assert missing["mentions"] is None and missing["reason"] == "incomplete_archive"
    observed = join_day(mentions, day, day, True)
    assert observed["mentions"] == 1 and observed["sources"] == 1
    assert observed["acquisition_mentions"] == 1
    quiet = join_day([], day, day, True)
    assert quiet["mentions"] == 0 and quiet["tone"] is None
    counts = {day - timedelta(days=offset): 0 for offset in range(14)}
    assert rolling_change(counts, day, 7) == 0
    del counts[day - timedelta(days=3)]
    assert rolling_change(counts, day, 7) is None
    assert day_complete(["a", "b"], ["b", "a"]) is True
    assert day_complete(["a", "b"], ["a"]) is False


if __name__ == "__main__":
    test_index_keeps_one_gkg_day_and_rejects_a_later_lookalike()
    test_rate_limit_is_not_retried_and_a_server_error_backs_off()
    test_publication_time_is_not_taken_from_the_processing_stamp_or_mentioned_dates()
    test_one_article_matches_a_company_once_and_a_later_copy_is_dropped()
    test_news_after_the_cutoff_is_not_zero_and_a_gap_is_not_zero()
    print("ok")
