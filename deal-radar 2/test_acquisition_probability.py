"""Leakage, missing probabilities, and the valuation handoff.

The tests use constructed rows. They do not read the historical database.
"""
import math
from datetime import date, timedelta

import black_scholes
import predictive.estimators as estimators
import predictive.metrics as metrics
import predictive.point_in_time as point
import predictive.valuation_link as link


def _bars(snapshot, sessions, start_close=100.0):
    bars = []
    for index in range(sessions):
        day = snapshot - timedelta(days=sessions - index)
        bars.append({"date": day, "close": start_close + index, "volume": 1000.0 + index})
    return bars


def test_later_prices_do_not_change_features():
    snapshot = date(2021, 6, 1)
    bars = _bars(snapshot, 100)
    future = {"date": snapshot + timedelta(days=1), "close": 900.0, "volume": 5000000.0}
    before = point.feature_row(snapshot, bars, bars, None)
    after = point.feature_row(snapshot, bars + [future], bars + [future], None)
    assert before["price_known"] is True
    assert before["return_30"] is not None
    assert before["volatility_30"] is not None
    assert before["volume_change_30"] is not None
    for key in ("return_7", "return_30", "return_90", "volume_change_7", "volume_change_30", "volatility_30"):
        assert before[key] == after[key]
    only_future = point.feature_row(snapshot, [future], [], None)
    assert only_future["price_known"] is False
    assert only_future["return_30"] is None


def test_a_later_filing_is_not_a_financial_feature():
    snapshot = date(2021, 6, 1)
    hidden = point.statement_features({"close": 20.0}, snapshot, {
        "assets": 100.0, "assets_filed": "2021-06-02",
        "shares": 10.0, "shares_filed": "2021-06-02",
        "latest_10k_date": "2021-06-02",
    })
    assert hidden["log_assets"] is None
    assert hidden["log_market_cap"] is None
    assert hidden["days_since_10k"] is None
    known = point.statement_features({"close": 20.0}, snapshot, {
        "assets": 100.0, "assets_filed": "2021-06-01",
        "equity": 40.0, "equity_filed": "2021-06-01",
        "shares": 10.0, "shares_filed": "2021-06-01",
        "latest_10k_date": "2021-05-01",
    })
    assert abs(known["log_assets"] - math.log(100.0)) < 1e-12
    assert abs(known["log_market_cap"] - math.log(200.0)) < 1e-12
    assert known["days_since_10k"] == 31


def test_news_keeps_zero_and_drops_other_dates():
    snapshot = date(2021, 2, 3)
    explicit = point.news_features({
        "snapshot_date": "2021-02-03", "reason": "observed",
        "mentions": 0, "sources": 0, "tone": None, "acquisition_mentions": 0,
    }, snapshot)
    assert explicit["news_observed"] == 1
    assert explicit["news_mentions"] == 0
    assert explicit["news_tone"] is None
    future = point.news_features({
        "snapshot_date": "2021-02-04", "reason": "observed", "mentions": 40,
    }, snapshot)
    assert future["news_observed"] == 0
    assert future["news_mentions"] is None
    earlier = point.news_features({
        "snapshot_date": "2021-02-02", "reason": "observed", "mentions": 5,
    }, snapshot)
    assert earlier["news_mentions"] is None
    withheld = point.news_features({
        "snapshot_date": "2021-02-03", "reason": "archive_after_cutoff", "mentions": None,
    }, snapshot)
    assert withheld["news_observed"] == 0
    assert withheld["news_mentions"] is None


def test_labels_and_the_vector_exclude_the_outcome():
    today = date(2026, 11, 9)
    announced = date(2021, 6, 30)
    positive = point.labels_for(announced - timedelta(days=30), announced, "target_pre", {}, today)
    assert positive[30] == 1 and positive[60] == 1 and positive[90] == 1
    inside_90 = point.labels_for(announced - timedelta(days=90), announced, "target_pre", {}, today)
    assert inside_90[30] == 0 and inside_90[60] == 0 and inside_90[90] == 1
    early = point.labels_for(announced - timedelta(days=180), announced, "target_pre", {}, today)
    assert early[30] == 0 and early[60] == 0 and early[90] == 0
    control = point.labels_for(date(2021, 1, 1), None, "non_acquired", {30: 0, 90: 0}, today)
    assert control[60] == 0
    unfinished = point.labels_for(date(2021, 1, 1), None, "non_acquired", {30: 0, 90: None}, today)
    assert unfinished[60] is None
    snapshot = date(2021, 6, 1)
    example = point.examine({
        "cik": 1, "ticker": "AAA", "snapshot_date": snapshot.isoformat(),
        "kind": "target_pre", "announcement_date": "2021-07-01",
        "label_30": 1, "label_90": 1, "assets": 5, "assets_filed": "2020-01-01",
    }, _bars(snapshot, 40), [], None, today)
    assert "announcement_date" not in example["features"]
    assert "kind" not in example["features"]
    names = point.column_plan(include_news=True)
    assert all("label" not in name and "announcement" not in name and "offer" not in name for name in names)
    vector = point.row_vector(example["features"], names)
    example["features"]["kind"] = "target_pre"
    example["features"]["label_30"] = 1
    assert point.row_vector(example["features"], names) == vector


def test_the_holdout_is_later_and_does_not_reuse_a_company():
    rows = []
    for cik, group in ((1, "2018-01-01"), (2, "2019-01-01"), (3, "2020-01-01"), (4, "2021-01-01"), (5, "2022-01-01")):
        rows.append({
            "cik": cik, "snapshot_date": "2017-06-01", "announcement_date": group,
        })
        rows.append({
            "cik": cik, "snapshot_date": group, "announcement_date": group,
        })
    rows.append({"cik": 5, "snapshot_date": "2016-01-01", "announcement_date": "2016-06-01"})
    split = point.chronological_split(rows)
    seen = {}
    for name in ("train", "validation", "test"):
        for row in split["folds"][name]:
            assert seen.get(row["cik"], name) == name
            seen[row["cik"]] = name
    assert set(seen) == {1, 2, 3, 4, 5}
    assert all(row["announcement_date"] >= "2022-01-01" for row in split["folds"]["test"])
    assert any(row["announcement_date"] == "2016-06-01" for row in split["folds"]["excluded"])
    assert max(row["group_date"] for row in split["folds"]["train"]) <= min(
        row["group_date"] for row in split["folds"]["test"]
    )


def test_constant_scores_have_no_ranking_skill():
    labels = [1, 0, 1, 0, 0, 1]
    scores = [0.4] * len(labels)
    assert abs(metrics.roc_auc(labels, scores) - 0.5) < 1e-12
    perfect = metrics.roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9])
    assert abs(perfect - 1) < 1e-12
    assert metrics.average_precision([], []) is None


def test_a_missing_probability_is_not_replaced():
    assumptions = {
        "spot": 50, "strike": 50, "rate": 0.05, "kind": "call",
        "standalone_volatility": 0.30, "deal_volatility": 0.15,
        "failure_probability": 0.25, "consideration": "cash",
        "acquisition_price": 60, "downside": 40,
        "days_to_expiration": 365, "days_to_close": 100, "days_to_announcement": 30,
    }
    missing = link.apply_probability(assumptions, None)
    assert missing["probability"] is None and missing["valuation"] is None
    assert "acquisition_probability" not in assumptions
    direct = black_scholes.acquisition_option_value(dict(assumptions))
    assert direct["expected"] is None
    rejected = link.probability_for_valuation(
        {"supply_to_valuation": False},
        {"probability": 0.25, "coverage_sufficient": True},
    )
    assert rejected is None
    uncovered = link.probability_for_valuation(
        {"supply_to_valuation": True},
        {"probability": 0.25, "coverage_sufficient": False},
    )
    assert uncovered is None
    accepted = link.apply_probability(assumptions, 0.25)
    again = black_scholes.acquisition_option_value(dict(assumptions, acquisition_probability=0.25))
    assert accepted["probability"] == 0.25
    assert abs(accepted["valuation"]["expected"] - again["expected"]) < 1e-12


def test_the_valuation_gate_rejects_a_case_control_sample():
    good_metrics = {
        "rows": 40, "positives": 10, "negatives": 30,
        "pr_auc": 0.40, "base_pr_auc": 0.25,
        "roc_auc": 0.70, "brier": 0.15, "base_brier": 0.20,
    }
    blocked = link.supply_decision(
        {"feature_lookahead_violations": 0, "market_wide_sample": False,
         "market_wide_reason": "The rows are a case-control extract."},
        good_metrics, good_metrics,
    )
    assert blocked["supply"] is False
    leaked = link.supply_decision(
        {"feature_lookahead_violations": 2, "market_wide_sample": True},
        good_metrics, good_metrics,
    )
    assert leaked["supply"] is False
    weak = dict(good_metrics, pr_auc=0.20, brier=0.25)
    no_lift = link.supply_decision(
        {"feature_lookahead_violations": 0, "market_wide_sample": True},
        good_metrics, weak,
    )
    assert no_lift["supply"] is False
    ready = link.supply_decision(
        {"feature_lookahead_violations": 0, "market_wide_sample": True},
        good_metrics, good_metrics,
    )
    assert ready["supply"] is True


def test_modules_do_not_call_the_filing_close_rule():
    for module in (point, estimators, link):
        text = open(module.__file__, encoding="utf-8").read()
        assert "close_probability" not in text
        assert "estimate_probabilities" not in text
        assert "0.90" not in text
        assert "0.93" not in text
    black = open(black_scholes.__file__, encoding="utf-8").read()
    assert "predictive.valuation_link" not in black
    assert "train_acquisition" not in black


def test_logistic_recovers_a_separating_direction():
    columns = ["signal"]
    rows = [[0.0], [0.1], [0.2], [1.0], [1.1], [1.2]]
    labels = [0, 0, 0, 1, 1, 1]
    fitted = estimators.fit_logistic(columns, rows, labels, C=1.0)
    low, high = fitted.predict([[0.0], [1.2]])
    assert high > low
    assert fitted.importance()[0]["weight"] > 0


if __name__ == "__main__":
    test_later_prices_do_not_change_features()
    test_a_later_filing_is_not_a_financial_feature()
    test_news_keeps_zero_and_drops_other_dates()
    test_labels_and_the_vector_exclude_the_outcome()
    test_the_holdout_is_later_and_does_not_reuse_a_company()
    test_constant_scores_have_no_ranking_skill()
    test_a_missing_probability_is_not_replaced()
    test_the_valuation_gate_rejects_a_case_control_sample()
    test_modules_do_not_call_the_filing_close_rule()
    test_logistic_recovers_a_separating_direction()
    print("ok")
