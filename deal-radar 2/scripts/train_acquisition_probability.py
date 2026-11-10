"""Train the 30, 60, and 90 day acquisition models on the stored history.

    python3 scripts/train_acquisition_probability.py

The fit uses prices, financials, and news already on disk. It does not change
the announced-deal closing probability, Black-Scholes, or the live page.
A probability is marked usable for valuation only when the holdout and the
sample design both pass. Otherwise the saved experiment supplies nothing.
"""
import json
import os
import sys
from collections import Counter
from datetime import date, datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from historical.prices import fetch_yahoo
from historical.store import connect
from predictive.estimators import candidates, fit_candidate
from predictive.gates import acquisition_ready
from predictive.metrics import evaluate
from predictive.point_in_time import (
    as_date, chronological_split, column_plan, examine, feature_row, last_index, row_vector,
)
from predictive.valuation_link import supply_decision

DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
NEWS_DB = os.path.join(ROOT, "data", "historical", "gdelt_bulk", "pilot.sqlite")
OUT = os.path.join(ROOT, "data", "predictive")
REPORTS = os.path.join(ROOT, "reports")
MARKET_CACHE = os.path.join(OUT, "spy_bars.json")
EXPERIMENT = os.path.join(OUT, "acquisition_experiment.json")
NEWS_MIN = 20
HORIZONS = (30, 60, 90)


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt(value, digits=4):
    if value is None:
        return "not computed"
    if isinstance(value, float):
        return ("%." + str(digits) + "f") % value
    return str(value)


def load_prices(conn):
    rows = conn.execute(
        """SELECT ticker, bar_date, close, adj_close, volume
           FROM historical_stock_prices WHERE source='yahoo-chart'"""
    ).fetchall()
    adjusted = sum(1 for row in rows if row["adj_close"] is not None)
    use_adjusted = bool(rows) and adjusted >= 0.95 * len(rows)
    series = {}
    for row in rows:
        price = row["adj_close"] if use_adjusted and row["adj_close"] is not None else row["close"]
        if price is None:
            continue
        series.setdefault(row["ticker"], []).append({
            "date": date.fromisoformat(row["bar_date"]),
            "close": float(price),
            "volume": None if row["volume"] is None else float(row["volume"]),
        })
    for ticker in series:
        series[ticker].sort(key=lambda bar: bar["date"])
    return series, {
        "rows": len(rows),
        "tickers": len(series),
        "adjusted_rows": adjusted,
        "price_field": "adj_close" if use_adjusted else "close",
    }


def load_market():
    if os.path.exists(MARKET_CACHE):
        payload = json.loads(open(MARKET_CACHE, encoding="utf-8").read())
        bars = [{"date": date.fromisoformat(item["date"]), "close": item["close"], "volume": None}
                for item in payload.get("bars") or []]
        bars.sort(key=lambda bar: bar["date"])
        return bars, payload.get("note") or "Cached S&P 500 ETF bars."
    try:
        parsed = fetch_yahoo("SPY", date(2014, 11, 1), date.today())
    except Exception as exc:
        return [], "SPY was not fetched: %s" % exc
    if parsed.get("error") or not parsed.get("bars"):
        return [], "SPY chart returned no bars (%s)." % (parsed.get("error") or parsed.get("httpStatus"))
    bars = [{"date": bar["date"], "close": bar["close"], "volume": None} for bar in parsed["bars"] if bar.get("close")]
    bars.sort(key=lambda bar: bar["date"])
    os.makedirs(OUT, exist_ok=True)
    with open(MARKET_CACHE, "w", encoding="utf-8") as handle:
        json.dump({
            "symbol": "SPY",
            "source": "yahoo-chart",
            "note": "S&P 500 ETF daily closes, used only as the market return. Retrieved %s." % iso_now(),
            "bars": [{"date": bar["date"].isoformat(), "close": bar["close"]} for bar in bars],
        }, handle)
    return bars, "Fetched %d SPY closes from the Yahoo chart and cached them." % len(bars)


def load_news():
    if not os.path.exists(NEWS_DB):
        return {}, "The GDELT pilot database is not on disk."
    import sqlite3
    conn = sqlite3.connect(NEWS_DB)
    conn.row_factory = sqlite3.Row
    found = {}
    for row in conn.execute("SELECT * FROM features"):
        found[(row["cik"], row["snapshot_date"])] = dict(row)
    conn.close()
    return found, "GDELT pilot feature rows: %d." % len(found)


def load_snapshots(conn):
    rows = [dict(row) for row in conn.execute(
        """SELECT cik, ticker, snapshot_date, kind, announcement_adsh, announcement_date,
                  label_30, label_90, label_180, last_close_date, latest_10k_date,
                  revenue, revenue_filed, assets, assets_filed, cash, cash_filed,
                  equity, equity_filed, debt, debt_filed, shares, shares_filed
           FROM historical_company_snapshots"""
    )]
    names = {row["adsh"]: row["target_name"] for row in conn.execute(
        "SELECT adsh, target_name FROM historical_ma_transactions"
    )}
    return rows, names


def database_counts(conn):
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "search_hits": one("SELECT COUNT(*) FROM search_hits"),
        "verified_transactions": one(
            """SELECT COUNT(*) FROM historical_ma_transactions
               WHERE role='target' AND is_amendment=0 AND duplicate_of IS NULL"""
        ),
        "unread_hits": one(
            """SELECT COUNT(*) FROM search_hits
               WHERE text_status IS NULL AND form NOT LIKE '%/A' AND items LIKE '%1.01%'"""
        ),
        "news_table_rows": one("SELECT COUNT(*) FROM historical_news_signals"),
        "missing_target_ticker": one(
            """SELECT COUNT(*) FROM historical_ma_transactions
               WHERE role='target' AND is_amendment=0 AND duplicate_of IS NULL
                 AND (target_ticker IS NULL OR target_ticker='')"""
        ),
    }


def future_stored_fields(rows):
    future_close = future_filing = 0
    for row in rows:
        snapshot = as_date(row.get("snapshot_date"))
        close_on = as_date(row.get("last_close_date"))
        if snapshot and close_on and close_on > snapshot:
            future_close += 1
        for field in ("revenue_filed", "assets_filed", "cash_filed", "equity_filed", "debt_filed", "shares_filed"):
            filed = as_date(row.get(field))
            if snapshot and filed and filed > snapshot:
                future_filing += 1
                break
        filed_10k = as_date(row.get("latest_10k_date"))
        if snapshot and filed_10k and filed_10k > snapshot:
            future_filing += 1
    return future_close, future_filing


def build_examples(rows, names, prices, market, news):
    today = date.today()
    examples = []
    for row in rows:
        ticker = row.get("ticker") or None
        if row.get("cik") is None:
            reason = "no_cik"
            bars = []
        elif not ticker:
            reason = "no_ticker"
            bars = []
        elif ticker not in prices:
            reason = "no_bars"
            bars = []
        else:
            bars = prices[ticker]
            reason = None
        record = news.get((row.get("cik"), row.get("snapshot_date")))
        example = examine(row, bars, market, record, today, names.get(row.get("announcement_adsh")))
        if reason is None:
            reason = "priced" if example["price_known"] else "no_bar_on_or_before"
        example["exclusion"] = reason
        examples.append(example)
    return examples


def lookahead_mismatches(examples, prices, market, news):
    """Recompute features with every later bar removed. A difference is look-ahead."""
    mismatches = 0
    checked = 0
    for example in examples:
        if not example["price_known"] or not example.get("ticker"):
            continue
        snapshot = as_date(example["snapshot_date"])
        bars = prices[example["ticker"]]
        cut = last_index(bars, snapshot)
        market_cut = last_index(market, snapshot) if market else -1
        again = feature_row(
            snapshot,
            bars[:cut + 1],
            market[:market_cut + 1] if market_cut >= 0 else [],
            news.get((example["cik"], example["snapshot_date"])),
        )
        checked += 1
        original = example["features"]
        for key in ("return_7", "return_30", "return_90", "volume_change_7", "volume_change_30", "volatility_30"):
            if again.get(key) != original.get(key):
                mismatches += 1
                break
    return mismatches, checked


def vectors(rows, names):
    return [row_vector(row["features"], names) for row in rows]


def labeled(rows, horizon):
    return [row for row in rows if row["labels"].get(horizon) in (0, 1)]


def train_rate(rows, horizon):
    labels = [row["labels"][horizon] for row in rows]
    if not labels:
        return None
    return sum(labels) / float(len(labels))


def fit_family(family, params_list, columns, train_rows, valid_rows, horizon):
    best = None
    best_score = None
    train_y = [row["labels"][horizon] for row in train_rows]
    valid_y = [row["labels"][horizon] for row in valid_rows]
    rate = train_rate(train_rows, horizon)
    for params in params_list:
        fitted = fit_candidate(family, params, columns, vectors(train_rows, columns), train_y)
        if fitted is None:
            continue
        scored = evaluate(valid_y, fitted.predict(vectors(valid_rows, columns)), rate)
        if scored["pr_auc"] is None:
            continue
        rank = (scored["pr_auc"], -scored["brier"] if scored["brier"] is not None else 0)
        if best_score is None or rank > best_score:
            best = fitted
            best_score = rank
            best.validation = scored
    return best


def score_fold(fitted, rows, horizon, rate):
    labels = [row["labels"][horizon] for row in rows]
    scores = fitted.predict(vectors(rows, fitted.columns))
    return evaluate(labels, scores, rate), scores


def top_features(fitted, limit=8):
    rows = fitted.importance()
    if not rows:
        return []
    key = "weight" if "weight" in rows[0] else "importance"
    rows.sort(key=lambda item: abs(item.get(key) or 0), reverse=True)
    return rows[:limit]


def fold_span(rows):
    if not rows:
        return None, None
    dates = [row["group_date"] for row in rows]
    return min(dates), max(dates)


def write_reports(audit, comparison, evaluation, generated):
    os.makedirs(REPORTS, exist_ok=True)
    audit_path = os.path.join(REPORTS, "acquisition_dataset_audit.md")
    comparison_path = os.path.join(REPORTS, "acquisition_model_comparison.md")
    evaluation_path = os.path.join(REPORTS, "acquisition_oos_evaluation.md")
    with open(audit_path, "w", encoding="utf-8") as handle:
        handle.write(render_audit(audit, generated))
    with open(comparison_path, "w", encoding="utf-8") as handle:
        handle.write(render_comparison(comparison, generated))
    with open(evaluation_path, "w", encoding="utf-8") as handle:
        handle.write(render_evaluation(evaluation, generated))
    return audit_path, comparison_path, evaluation_path


def bullet_counts(pairs):
    return "\n".join("- %s: %s" % (name, value) for name, value in pairs)


def render_audit(audit, generated):
    coverage_lines = [
        "- %s: %d of %d modeling rows" % (name, count, audit["modeled_30"])
        for name, count in audit["coverage_30"]
    ]
    lines = [
        "# Historical acquisition dataset audit",
        "",
        "Generated %s, before the model fit. No live probability was changed." % generated,
        "",
        "## What is on disk",
        "",
        bullet_counts([
            ("SEC search hits", audit["search_hits"]),
            ("Verified target transactions", audit["verified_transactions"]),
            ("Verified transactions missing a target ticker", audit["missing_target_ticker"]),
            ("Unread item 1.01 hits", audit["unread_hits"]),
            ("Company snapshots", audit["snapshots"]),
            ("Distinct companies in the snapshots", audit["companies"]),
            ("Target snapshots", audit["target_snapshots"]),
            ("Non-acquired snapshots", audit["control_snapshots"]),
            ("Stored Yahoo bars", "%s across %s tickers" % (audit["price_rows"], audit["price_tickers"])),
            ("Price field used for returns", audit["price_field"]),
            ("Adjusted closes stored", audit["adjusted_rows"]),
            ("Rows in historical_news_signals", audit["news_table_rows"]),
            ("GDELT pilot feature rows", audit["news_pilot_rows"]),
            ("Market series", audit["market_note"]),
        ]),
        "",
        "## Snapshot dates",
        "",
        "- Earliest snapshot: %s" % audit["snapshot_min"],
        "- Latest snapshot: %s" % audit["snapshot_max"],
        "- Announcement span: %s to %s" % (audit["announcement_min"], audit["announcement_max"]),
        "- Target snapshot offsets: %s" % ", ".join("%s days (%s rows)" % (gap, count) for gap, count in audit["gaps"]),
        "",
        "## Rows that can be modeled",
        "",
        "A row is modeled only when it has a ticker and a price bar on or before the snapshot. A missing ticker is not used as a feature, because missing tickers are more common where the filing parser failed.",
        "",
        bullet_counts(audit["waterfall"]),
        "",
        "30-day labels among priced rows: %d positives, %d negatives, %d censored." % (
            audit["positives_30"], audit["negatives_30"], audit["censored_30"]),
        "60-day labels among priced rows: %d positives, %d negatives, %d censored." % (
            audit["positives_60"], audit["negatives_60"], audit["censored_60"]),
        "90-day labels among priced rows: %d positives, %d negatives, %d censored." % (
            audit["positives_90"], audit["negatives_90"], audit["censored_90"]),
        "",
        "## Feature coverage on priced 30-day rows",
        "",
        "\n".join(coverage_lines) if coverage_lines else "- No priced 30-day rows.",
        "",
        "GDELT observations attached to a priced row: %d. A day with no matched article is an explicit zero. A company that was not in the pilot is missing, not zero. Rolling 7, 30, and 90 day news changes are missing for every row because the pilot archive is one UTC day." % audit["news_observed_priced"],
        "",
        "## Data-quality limits",
        "",
    ]
    for note in audit["limitations"]:
        lines.append("- %s" % note)
    lines.extend([
        "",
        "## Look-ahead check",
        "",
        "- Stored last-close dates after the snapshot: %d" % audit["future_close_dates"],
        "- Stored financial filed dates after the snapshot: %d" % audit["future_filings"],
        "- Features that changed when later price bars were removed: %d of %d priced rows" % (
            audit["feature_lookahead_violations"], audit["lookahead_rows_checked"]),
        "- Market-wide sample: %s" % ("yes" if audit["market_wide_sample"] else "no"),
        "- %s" % audit["market_wide_reason"],
        "",
    ])
    return "\n".join(lines)


def render_comparison(comparison, generated):
    lines = [
        "# Acquisition model comparison",
        "",
        "Generated %s. The model family was chosen on the validation fold. The holdout numbers below were not used to choose it." % generated,
        "",
        comparison["setup"],
        "",
    ]
    for horizon in HORIZONS:
        block = comparison["horizons"].get(horizon)
        lines.append("## %d-day horizon" % horizon)
        lines.append("")
        if not block:
            lines.append("This horizon was not fit.")
            lines.append("")
            continue
        if block.get("skipped"):
            lines.append(block["skipped"])
            lines.append("")
            continue
        lines.append("Training companies %d, validation %d, holdout %d. Training positive rate %s." % (
            block["companies"]["train"], block["companies"]["validation"], block["companies"]["test"],
            fmt(block["train_rate"])))
        lines.append("Group dates: train %s to %s, validation %s to %s, holdout %s to %s." % (
            block["spans"]["train"][0], block["spans"]["train"][1],
            block["spans"]["validation"][0], block["spans"]["validation"][1],
            block["spans"]["test"][0], block["spans"]["test"][1]))
        lines.append("")
        lines.append("| Model | Validation PR-AUC | Validation ROC-AUC | Validation Brier | Holdout PR-AUC | Holdout ROC-AUC | Holdout Brier |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        lines.append("| Training base rate | %s | 0.5000 | %s | %s | 0.5000 | %s |" % (
            fmt(block["baseline"]["validation"]["base_pr_auc"]),
            fmt(block["baseline"]["validation"]["base_brier"]),
            fmt(block["baseline"]["test"]["base_pr_auc"]),
            fmt(block["baseline"]["test"]["base_brier"]),
        ))
        for item in block["models"]:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                item["name"],
                fmt(item["validation"]["pr_auc"]), fmt(item["validation"]["roc_auc"]), fmt(item["validation"]["brier"]),
                fmt(item["test"]["pr_auc"]), fmt(item["test"]["roc_auc"]), fmt(item["test"]["brier"]),
            ))
        lines.append("")
        lines.append("Selected on validation: %s." % block["selected"])
        lines.append("")
    lines.append("## News features")
    lines.append("")
    lines.append(comparison["news"])
    lines.append("")
    lines.append("The announced-deal closing probability and black_scholes.py were not modified.")
    lines.append("")
    return "\n".join(lines)


def render_evaluation(evaluation, generated):
    lines = [
        "# Out-of-sample acquisition evaluation",
        "",
        "Generated %s." % generated,
        "",
        evaluation["claim"],
        "",
    ]
    for horizon in HORIZONS:
        block = evaluation["horizons"].get(horizon)
        lines.append("## %d-day holdout" % horizon)
        lines.append("")
        if not block or block.get("skipped"):
            lines.append(block.get("skipped") if block else "Not fit.")
            lines.append("")
            continue
        test = block["test"]
        lines.append("Model: %s." % block["selected"])
        lines.append("Holdout rows %d, positives %d, negatives %d, positive rate %s." % (
            test["rows"], test["positives"], test["negatives"], fmt(test["prevalence"])))
        lines.append("")
        lines.append("- PR-AUC: %s. Base rate: %s." % (fmt(test["pr_auc"]), fmt(test["base_pr_auc"])))
        lines.append("- ROC-AUC: %s. Constant-score ROC-AUC: 0.5000." % fmt(test["roc_auc"]))
        lines.append("- Brier score: %s. Training-rate Brier score: %s." % (fmt(test["brier"]), fmt(test["base_brier"])))
        half = test["at_half"] or {}
        base = test["at_base_rate"] or {}
        lines.append("- Precision / recall at 0.50: %s / %s." % (fmt(half.get("precision")), fmt(half.get("recall"))))
        lines.append("- Precision / recall at the training positive rate: %s / %s." % (
            fmt(base.get("precision")), fmt(base.get("recall"))))
        lines.append("- Precision in the top %d holdout rows: %s." % (test["top_10"], fmt(test["precision_top_10"])))
        lines.append("- Precision in the top 5 percent (%d rows): %s." % (test["top_5pct"], fmt(test["precision_top_5pct"])))
        lines.append("")
        if test["calibration"]:
            lines.append("Calibration, lowest predicted score to highest:")
            lines.append("")
            for bucket in test["calibration"]:
                lines.append("- %d rows, mean predicted %s, observed rate %s" % (
                    bucket["n"], fmt(bucket["mean_predicted"]), fmt(bucket["observed_rate"])))
            lines.append("")
    lines.append("## Contributing features for the 30-day model")
    lines.append("")
    if evaluation["features"]:
        lines.append("These are training-sample associations. They are not causes.")
        lines.append("")
        for item in evaluation["features"]:
            if "weight" in item:
                lines.append("- %s: standardized weight %s" % (item["feature"], fmt(item["weight"])))
            else:
                lines.append("- %s: importance %s" % (item["feature"], fmt(item["importance"])))
    else:
        lines.append("No 30-day model was selected.")
    lines.extend(["", "## Highest 30-day scores in the holdout", ""])
    if not evaluation["ranks"]:
        lines.append("No holdout scores were produced.")
    else:
        lines.append("These are past prediction dates from the holdout, shown with the outcome so the ranking can be checked. They are not current recommendations.")
        lines.append("")
        lines.append("| Rank | Company | Prediction date | Probability | Announced within 30 days | Feature coverage | News observed |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for index, row in enumerate(evaluation["ranks"], start=1):
            company = row["ticker"] or ("CIK %s" % row["cik"])
            if row.get("name"):
                company = "%s (%s)" % (row["name"], company)
            lines.append("| %d | %s | %s | %s | %s | %s | %s |" % (
                index, company, row["snapshot_date"], fmt(row["probability"]),
                "yes" if row["label"] else "no", fmt(row["coverage"], 2),
                "yes" if row["news"] else "no",
            ))
    lines.extend([
        "",
        "## Valuation link",
        "",
        evaluation["valuation"],
        "",
        "A missing probability is left missing. The experiment file does not replace it with the filing close rate.",
        "",
    ])
    return "\n".join(lines)


def main():
    generated = iso_now()
    conn = connect(DB)
    counts = database_counts(conn)
    snapshots, names = load_snapshots(conn)
    prices, price_meta = load_prices(conn)
    conn.close()
    market, market_note = load_market()
    news, news_note = load_news()
    examples = build_examples(snapshots, names, prices, market, news)
    mismatches, checked = lookahead_mismatches(examples, prices, market, news)
    future_close, future_filing = future_stored_fields(snapshots)

    priced = [row for row in examples if row["exclusion"] == "priced" and row.get("cik") is not None]
    modeled = {}
    for horizon in HORIZONS:
        rows = labeled(priced, horizon)
        modeled[horizon] = {
            "rows": rows,
            "positives": sum(row["labels"][horizon] for row in rows),
            "negatives": sum(row["labels"][horizon] == 0 for row in rows),
            "censored": sum(row["labels"][horizon] is None for row in priced),
        }
    coverage_names = (
        ("30-day return", "return_30"), ("90-day return", "return_90"),
        ("30-day abnormal return", "abnormal_30"), ("30-day volume change", "volume_change_30"),
        ("30-session volatility", "volatility_30"), ("log market cap", "log_market_cap"),
        ("log assets", "log_assets"), ("observed news", "news_observed"),
    )
    priced_30 = modeled[30]["rows"]
    coverage_30 = []
    for label, key in coverage_names:
        if key == "news_observed":
            count = sum(row["features"].get(key) == 1 for row in priced_30)
        else:
            count = sum(row["features"].get(key) is not None for row in priced_30)
        coverage_30.append((label, count))
    gaps = Counter(row["gap_days"] for row in examples if row["kind"] == "target_pre")
    fixed_offset = set(gaps) <= {30, 90, 180} and gaps.get(30) and gaps.get(90) and gaps.get(180)
    positives_only_at_30 = all(
        row["gap_days"] == 30
        for row in examples
        if row["kind"] == "target_pre" and row["labels"].get(30) == 1
    )
    limitations = [
        "Target snapshots are the announcement date minus 30, 90, and 180 days. A 30-day positive is that 30-day offset.",
        "A non-acquired label means three EDGAR phrases returned no hit in the horizon. It does not prove the company was never acquired.",
        "Unread item 1.01 hits: %d. Verified transactions: %d. The acquired set is the portion of the search that was read." % (
            counts["unread_hits"], counts["verified_transactions"]),
        "Distinct non-acquired companies: %d." % sum(row["kind"] == "non_acquired" for row in examples),
        "Repeated snapshots of one deal are not independent companies.",
        "Yahoo closes are unadjusted except where the stored adjusted close was complete. Delisted symbols are missing when Yahoo has no series.",
        news_note,
        "historical_news_signals has %d rows." % counts["news_table_rows"],
        market_note,
    ]
    market_reasons = []
    if fixed_offset and positives_only_at_30:
        market_reasons.append(
            "Acquired companies were sampled at fixed offsets before a known announcement, so the 30-day label is the sampling design."
        )
    if counts["unread_hits"] > counts["verified_transactions"]:
        market_reasons.append(
            "Unread item 1.01 hits (%d) exceed verified transactions (%d)." % (
                counts["unread_hits"], counts["verified_transactions"])
        )
    market_reasons.append(
        "Non-acquired labels come from an EDGAR phrase screen, not from a census of companies that stayed independent."
    )
    snapshot_dates = [row["snapshot_date"] for row in examples if row.get("snapshot_date")]
    announcement_dates = [row["announcement_date"] for row in examples if row.get("announcement_date")]
    waterfall = Counter(row["exclusion"] for row in examples)
    audit = {
        "search_hits": counts["search_hits"],
        "verified_transactions": counts["verified_transactions"],
        "missing_target_ticker": counts["missing_target_ticker"],
        "unread_hits": counts["unread_hits"],
        "snapshots": len(examples),
        "companies": len({row["cik"] for row in examples if row.get("cik") is not None}),
        "target_snapshots": sum(row["kind"] == "target_pre" for row in examples),
        "control_snapshots": sum(row["kind"] == "non_acquired" for row in examples),
        "price_rows": price_meta["rows"],
        "price_tickers": price_meta["tickers"],
        "adjusted_rows": price_meta["adjusted_rows"],
        "price_field": price_meta["price_field"],
        "news_table_rows": counts["news_table_rows"],
        "news_pilot_rows": len(news),
        "market_note": market_note,
        "snapshot_min": min(snapshot_dates) if snapshot_dates else None,
        "snapshot_max": max(snapshot_dates) if snapshot_dates else None,
        "announcement_min": min(announcement_dates) if announcement_dates else None,
        "announcement_max": max(announcement_dates) if announcement_dates else None,
        "gaps": sorted((gap, count) for gap, count in gaps.items()),
        "waterfall": (
            ("No CIK", waterfall.get("no_cik", 0)),
            ("No ticker", waterfall.get("no_ticker", 0)),
            ("Ticker with no stored bars", waterfall.get("no_bars", 0)),
            ("Bars only after the snapshot", waterfall.get("no_bar_on_or_before", 0)),
            ("Price known on the snapshot", waterfall.get("priced", 0)),
        ),
        "positives_30": modeled[30]["positives"],
        "negatives_30": modeled[30]["negatives"],
        "censored_30": modeled[30]["censored"],
        "positives_60": modeled[60]["positives"],
        "negatives_60": modeled[60]["negatives"],
        "censored_60": modeled[60]["censored"],
        "positives_90": modeled[90]["positives"],
        "negatives_90": modeled[90]["negatives"],
        "censored_90": modeled[90]["censored"],
        "modeled_30": len(priced_30),
        "coverage_30": coverage_30,
        "news_observed_priced": sum(row["features"].get("news_observed") == 1 for row in priced),
        "limitations": limitations,
        "future_close_dates": future_close,
        "future_filings": future_filing,
        "feature_lookahead_violations": mismatches,
        "lookahead_rows_checked": checked,
        "market_wide_sample": not market_reasons,
        "market_wide_reason": " ".join(market_reasons) if market_reasons else "The sample passed the market-wide checks.",
    }

    columns = column_plan(include_news=False)
    forbidden = [name for name in columns if any(token in name for token in ("label", "announcement", "offer", "kind", "gap"))]
    if forbidden:
        raise SystemExit("Refusing to fit. A feature column is not point-in-time: %s" % ", ".join(forbidden))
    split_rows = [row for row in priced if any(row["labels"].get(horizon) in (0, 1) for horizon in HORIZONS)]
    split = chronological_split(split_rows) if len({row["cik"] for row in split_rows}) >= 3 else None

    comparison = {
        "setup": (
            "Companies are ordered by their latest announcement date, or by snapshot date when they have no announcement. "
            "The earliest 60 percent train, the next 20 percent validate, and the latest 20 percent are the holdout. "
            "A company is never in two folds. An earlier deal for a holdout or validation company is dropped, "
            "so a 2020 prediction is not scored as part of a later holdout. "
            "News columns are left out of these models unless the news section says they were fit."
        ),
        "horizons": {},
        "news": "",
    }
    evaluation = {"horizons": {}, "features": [], "ranks": [], "claim": "", "valuation": ""}
    selected_30 = None
    decision = {"supply": False, "reasons": [audit["market_wide_reason"]]}

    for horizon in HORIZONS:
        rows = labeled(priced, horizon)
        positives = sum(row["labels"][horizon] for row in rows)
        if horizon == 60:
            by_key = {
                (row["cik"], row["snapshot_date"]): row["labels"][30]
                for row in labeled(priced, 30)
            }
            comparable = [
                row for row in rows
                if (row["cik"], row["snapshot_date"]) in by_key
            ]
            differ = sum(row["labels"][60] != by_key[(row["cik"], row["snapshot_date"])] for row in comparable)
            if comparable and differ == 0:
                message = (
                    "Not fit. No stored snapshot falls 31 to 60 days before an announcement, "
                    "so the 60-day label matches the 30-day label on all %d comparable rows. "
                    "A separate 60-day probability was not produced."
                    % len(comparable)
                )
                comparison["horizons"][horizon] = {"skipped": message}
                evaluation["horizons"][horizon] = {"skipped": message}
                continue
        if split is None:
            message = "Not enough companies to make a chronological split."
            comparison["horizons"][horizon] = {"skipped": message}
            evaluation["horizons"][horizon] = {"skipped": message}
            continue
        folds = {name: labeled(split["folds"][name], horizon) for name in ("train", "validation", "test")}
        ready, missing = acquisition_ready({
            "rows": len(rows),
            "positives": positives,
            "negatives": len(rows) - positives,
            "holdout": len(folds["test"]),
        })
        if not ready or len({row["labels"][horizon] for row in folds["train"]}) < 2:
            message = "Not fit. The sample gate is missing %s." % ", ".join(missing or ["two training classes"])
            comparison["horizons"][horizon] = {"skipped": message}
            evaluation["horizons"][horizon] = {"skipped": message}
            continue
        rate = train_rate(folds["train"], horizon)
        by_family = {}
        for family, params in candidates():
            by_family.setdefault(family, []).append(params)
        chosen = []
        for family, params_list in by_family.items():
            fitted = fit_family(family, params_list, columns, folds["train"], folds["validation"], horizon)
            if fitted is None:
                continue
            fitted.test, _scores = score_fold(fitted, folds["test"], horizon, rate)
            chosen.append(fitted)
        if not chosen:
            message = "No model could be fit on this horizon."
            comparison["horizons"][horizon] = {"skipped": message}
            evaluation["horizons"][horizon] = {"skipped": message}
            continue
        chosen.sort(key=lambda item: (item.validation["pr_auc"], -(item.validation["brier"] or 0)), reverse=True)
        winner = chosen[0]
        block = {
            "companies": {name: len({row["cik"] for row in folds[name]}) for name in folds},
            "train_rate": rate,
            "spans": {name: fold_span(folds[name]) for name in folds},
            "baseline": {
                "validation": evaluate([row["labels"][horizon] for row in folds["validation"]], [rate] * len(folds["validation"]), rate),
                "test": evaluate([row["labels"][horizon] for row in folds["test"]], [rate] * len(folds["test"]), rate),
            },
            "models": [{
                "name": item.name,
                "validation": item.validation,
                "test": item.test,
            } for item in chosen],
            "selected": winner.name,
        }
        comparison["horizons"][horizon] = block
        evaluation["horizons"][horizon] = {"selected": winner.name, "test": winner.test, "validation": winner.validation}
        if horizon == 30:
            selected_30 = winner
            _scored, scores = score_fold(winner, folds["test"], horizon, rate)
            for row, score in zip(folds["test"], scores):
                row["score_30"] = score
            decision = supply_decision(audit, winner.validation, winner.test)
            evaluation["features"] = top_features(winner)
            ranked = sorted(folds["test"], key=lambda row: (-(row.get("score_30") or 0), row["snapshot_date"]))
            evaluation["ranks"] = [{
                "name": row["name"],
                "ticker": row["ticker"],
                "cik": row["cik"],
                "snapshot_date": row["snapshot_date"],
                "probability": row.get("score_30"),
                "label": row["labels"][30],
                "coverage": row["coverage"]["fraction"],
                "news": row["features"].get("news_observed") == 1,
            } for row in ranked[:15]]

    observed_train = 0
    if split is not None:
        observed_train = sum(row["features"].get("news_observed") == 1 for row in split["folds"]["train"])
    if observed_train < NEWS_MIN:
        comparison["news"] = (
            "The news model was not fit. Training rows with a GDELT observation on the prediction date: %d. "
            "The minimum used here is %d. Missing news was not filled with zero, and the price models above do not contain news columns. "
            "A with-news versus without-news score is not available."
            % (observed_train, NEWS_MIN)
        )
    else:
        comparison["news"] = "News coverage cleared the minimum. This run's selector still has to be extended before a news model is reported."

    if selected_30 is None:
        claim = "No 30-day model was fit, so no predictive accuracy is claimed."
    elif not decision["supply"]:
        claim = (
            "No predictive accuracy is claimed for screening companies or for option valuation. "
            + " ".join(decision["reasons"])
        )
    else:
        claim = (
            "The selected 30-day model beat the base rate on the validation fold and on the later holdout. "
            "That result is limited to the sample described in the audit."
        )
    evaluation["claim"] = claim
    if decision["supply"]:
        evaluation["valuation"] = (
            "The 30-day probability can be passed into the acquisition-aware Black-Scholes valuation when the company has a 30-day return and 30-session volatility. "
            "Rows without that coverage still receive no probability."
        )
    else:
        evaluation["valuation"] = (
            "The predicted probability was not connected to the acquisition-aware valuation. "
            + " ".join(decision["reasons"])
        )

    os.makedirs(OUT, exist_ok=True)
    experiment = {
        "generatedAt": generated,
        "task": "acquisition announcement within 30, 60, and 90 days",
        "supply_to_valuation": decision["supply"],
        "reasons": decision["reasons"],
        "selected30": None if selected_30 is None else selected_30.name,
        "marketWideSample": audit["market_wide_sample"],
        "featureLookaheadViolations": audit["feature_lookahead_violations"],
        "columns": columns,
    }
    with open(EXPERIMENT, "w", encoding="utf-8") as handle:
        json.dump(experiment, handle, indent=2)
    paths = write_reports(audit, comparison, evaluation, generated)
    print(claim)
    print("supply_to_valuation", decision["supply"])
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
