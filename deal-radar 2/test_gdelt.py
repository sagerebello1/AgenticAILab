"""GDELT feature rules. These checks do not call the network and do not fit a model."""
from datetime import date, timedelta

from historical.gdelt import (
    DOC_COVERAGE_START,
    articles_on_or_before,
    average_precision,
    brier,
    classification,
    feature_row,
    identity,
    keyword_query,
    mention_query,
    on_or_before,
    parse_articles,
    parse_timeline,
)


def _days(start, values):
    rows = []
    for offset, value in enumerate(values):
        day = start + timedelta(days=offset)
        rows.append({
            "bucket_date": day,
            "bucket_at": day.strftime("%Y-%m-%dT00:00:00Z"),
            "value": value,
        })
    return rows


def test_short_or_generic_names_are_not_queried():
    assert identity("KELLOGG CO", "K")["status"] == "queryable"
    assert identity("KELLOGG CO", "K")["ticker_term"] is None
    assert identity("", "AAPL")["status"] == "missing_name"
    assert identity("THE BANK", "BANK")["status"] == "ambiguous"
    phrase = identity("Otis Worldwide Corp", "OTIS")
    assert phrase["status"] == "queryable"
    assert "OTIS" in mention_query(phrase["phrase"], phrase["ticker_term"])
    assert " sourcelang:english" in keyword_query(phrase["phrase"], phrase["ticker_term"])
    assert "strategic review" in keyword_query(phrase["phrase"], phrase["ticker_term"])


def test_a_missing_day_is_not_zero_and_a_returned_zero_is_zero():
    snapshot = date(2020, 6, 30)
    start = snapshot - timedelta(days=59)
    full = _days(start, [0] * 60)
    gap = _days(snapshot - timedelta(days=29), [1] * 30)
    del gap[10]
    features = feature_row(full, [], full, snapshot)
    assert features["mentions_30"] == 0
    assert features["keywords_30"] == 0
    assert feature_row(gap, [], full, snapshot)["mentions_30"] is None
    assert feature_row(full, [], full, snapshot)["change_30"] == 0
    assert DOC_COVERAGE_START == date(2017, 1, 1)


def test_buckets_and_articles_after_the_snapshot_are_excluded():
    snapshot = date(2020, 6, 30)
    points = [
        {"bucket_date": snapshot, "value": 2},
        {"bucket_date": snapshot + timedelta(days=1), "value": 99},
    ]
    assert on_or_before(points, snapshot) == [points[0]]
    articles = parse_articles({"articles": [
        {"title": "Before", "seendate": "20200630T120000Z", "url": "https://example.test/a"},
        {"title": "After", "seendate": "20200701T120000Z", "url": "https://example.test/b"},
    ]})
    kept = articles_on_or_before(articles, snapshot)
    assert [row["title"] for row in kept] == ["Before"]
    assert kept[0]["published_at"] is None
    assert kept[0]["seen_at"] == "2020-06-30T12:00:00Z"


def test_timeline_values_are_copied_and_tone_is_not_filled():
    payload = {"timeline": [{"data": [
        {"date": "20200601T000000Z", "value": 4, "norm": 100},
        {"date": "20200602T000000Z", "value": 0, "norm": 80},
    ]}]}
    points = parse_timeline(payload)
    assert points[0]["value"] == 4 and points[0]["norm"] == 100
    assert points[1]["value"] == 0
    snapshot = date(2020, 6, 2)
    mentions = _days(snapshot - timedelta(days=29), [1] * 30)
    keywords = _days(snapshot - timedelta(days=29), [0] * 30)
    tone = [{"bucket_date": snapshot, "bucket_at": "2020-06-02T00:00:00Z", "value": -5}]
    row = feature_row(mentions, tone, keywords, snapshot)
    assert row["tone_30"] == -5
    assert row["tone_7"] == -5
    assert feature_row(mentions, [], keywords, snapshot)["tone_30"] is None
    partial = []
    for hour in range(23):
        partial.append({
            "bucket_date": snapshot,
            "bucket_at": "2020-06-02T%02d:00:00Z" % hour,
            "value": 1,
        })
    assert feature_row(partial, [], [], snapshot)["mentions_7"] is None


def test_scores_match_a_known_ranking():
    labels = [1, 0, 1, 0]
    scores = [0.9, 0.8, 0.2, 0.1]
    assert abs(average_precision(labels, scores) - (1.0 + 2 / 3) / 2) < 1e-9
    assert brier([1, 0], [1, 0]) == 0
    scored = classification([1, 0, 1], [0.9, 0.2, 0.1], 0.5)
    assert scored["precision"] == 1
    assert abs(scored["recall"] - 0.5) < 1e-9


if __name__ == "__main__":
    test_short_or_generic_names_are_not_queried()
    test_a_missing_day_is_not_zero_and_a_returned_zero_is_zero()
    test_buckets_and_articles_after_the_snapshot_are_excluded()
    test_timeline_values_are_copied_and_tone_is_not_filled()
    test_scores_match_a_known_ranking()
    print("ok")
