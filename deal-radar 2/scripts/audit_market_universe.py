"""Ask whether the files on disk can support a market-wide acquisition test.

    python3 scripts/audit_market_universe.py

The script does not fit a model, does not write a negative label from a missing
filing, and does not change Black-Scholes or the live close probability.
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from historical.store import connect
from predictive.point_in_time import as_date, chronological_split, last_index
from predictive.universe import label_window, quarter_ends

DB = os.path.join(ROOT, "data", "historical", "ma.sqlite")
OUT = os.path.join(ROOT, "data", "predictive", "representative_universe.json")
REPORTS = os.path.join(ROOT, "reports")
VERIFIED = "role='target' AND is_amendment=0 AND duplicate_of IS NULL"
HORIZONS = (30, 60, 90)


def load(conn):
    snapshots = [dict(row) for row in conn.execute(
        """SELECT cik, ticker, snapshot_date, kind, announcement_adsh, announcement_date,
                  label_30, label_90, label_180, company_outcome
           FROM historical_company_snapshots"""
    )]
    announcements = defaultdict(list)
    for row in conn.execute(
        """SELECT target_cik, announcement_date FROM historical_ma_transactions
           WHERE %s AND target_cik IS NOT NULL AND announcement_date IS NOT NULL""" % VERIFIED
    ):
        announcements[row["target_cik"]].append(as_date(row["announcement_date"]))
    prices = defaultdict(list)
    for row in conn.execute(
        "SELECT ticker, bar_date FROM historical_stock_prices WHERE source='yahoo-chart'"
    ):
        prices[row["ticker"]].append(as_date(row["bar_date"]))
    for ticker in prices:
        prices[ticker].sort()
    coverage = [dict(row) for row in conn.execute(
        "SELECT status, COUNT(*) n FROM price_coverage GROUP BY status"
    )]
    return snapshots, announcements, prices, coverage


def counts(conn):
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    return {
        "verified": one("SELECT COUNT(*) FROM historical_ma_transactions WHERE %s" % VERIFIED),
        "verified_ciks": one(
            "SELECT COUNT(DISTINCT target_cik) FROM historical_ma_transactions WHERE %s AND target_cik IS NOT NULL" % VERIFIED
        ),
        "repeat_ciks": one(
            """SELECT COUNT(*) FROM (
                 SELECT target_cik FROM historical_ma_transactions
                 WHERE %s AND target_cik IS NOT NULL GROUP BY target_cik HAVING COUNT(*)>1)""" % VERIFIED
        ),
        "search_hits": one("SELECT COUNT(*) FROM search_hits"),
        "filings_read": one("SELECT COUNT(*) FROM search_hits WHERE text_status='read'"),
        "unread_101": one(
            """SELECT COUNT(*) FROM search_hits
               WHERE text_status IS NULL AND form NOT LIKE '%/A' AND items LIKE '%1.01%'"""
        ),
        "short_windows": one("SELECT COUNT(*) FROM ingest_windows WHERE note LIKE '%of reported%'"),
        "news_rows": one("SELECT COUNT(*) FROM historical_news_signals"),
        "submission_files": len(os.listdir(os.path.join(ROOT, "data", "historical", "submissions"))),
        "fact_files": len(os.listdir(os.path.join(ROOT, "data", "historical", "facts"))),
    }


def case_control_audit(snapshots, prices):
    priced = []
    for row in snapshots:
        bars = prices.get(row.get("ticker") or "")
        if not bars or row.get("cik") is None:
            continue
        if last_index([{"date": day} for day in bars], as_date(row["snapshot_date"])) < 0:
            continue
        priced.append(row)
    split = chronological_split(priced)
    folds = {name: split["folds"][name] for name in ("train", "validation", "test")}
    company_sets = {name: {row["cik"] for row in rows} for name, rows in folds.items()}
    overlap = {
        "train_validation": len(company_sets["train"] & company_sets["validation"]),
        "train_test": len(company_sets["train"] & company_sets["test"]),
        "validation_test": len(company_sets["validation"] & company_sets["test"]),
    }
    per_deal = defaultdict(int)
    for row in priced:
        if row.get("announcement_adsh"):
            per_deal[row["announcement_adsh"]] += 1
    multi_snapshot_deals = sum(count > 1 for count in per_deal.values())
    test_multi = defaultdict(int)
    for row in folds["test"]:
        if row.get("announcement_adsh"):
            test_multi[row["announcement_adsh"]] += 1
    return {
        "priced_rows": len(priced),
        "overlap": overlap,
        "excluded_rows": len(split["folds"]["excluded"]),
        "deals_with_multiple_priced_snapshots": multi_snapshot_deals,
        "holdout_deals_with_multiple_snapshots": sum(count > 1 for count in test_multi.values()),
        "fold_rows": {name: len(rows) for name, rows in folds.items()},
        "fold_companies": {name: len(company_sets[name]) for name in company_sets},
    }


def price_spans(prices):
    spans = []
    for bars in prices.values():
        if bars:
            spans.append((bars[-1] - bars[0]).days)
    spans.sort()
    if not spans:
        return {"tickers": 0}
    return {
        "tickers": len(spans),
        "min_days": spans[0],
        "median_days": spans[len(spans) // 2],
        "max_days": spans[-1],
        "under_one_year": sum(span < 365 for span in spans),
    }


def grid(snapshots, announcements, prices, today):
    """Quarterly dates for stored tickers. Missing deals are left unlabeled."""
    by_ticker = defaultdict(set)
    for row in snapshots:
        if row.get("ticker") and row.get("cik") is not None:
            by_ticker[row["ticker"]].add(row["cik"])
    conflicts = [ticker for ticker, ciks in by_ticker.items() if len(ciks) > 1]
    dates = quarter_ends(2016, today)
    tally = {horizon: {"positive": 0, "unlabeled": 0, "censored": 0, "no_price": 0} for horizon in HORIZONS}
    companies_used = 0
    positives = {horizon: [] for horizon in HORIZONS}
    for ticker, bars in prices.items():
        ciks = by_ticker.get(ticker)
        if not ciks or len(ciks) != 1 or not bars:
            continue
        cik = next(iter(ciks))
        companies_used += 1
        deals = announcements.get(cik, [])
        indexed = [{"date": day} for day in bars]
        for snapshot in dates:
            if last_index(indexed, snapshot) < 0:
                for horizon in HORIZONS:
                    tally[horizon]["no_price"] += 1
                continue
            for horizon in HORIZONS:
                label, reason = label_window(deals, snapshot, horizon, today, record_complete=False)
                if label == 1:
                    tally[horizon]["positive"] += 1
                    if len(positives[horizon]) < 12:
                        positives[horizon].append({
                            "cik": cik, "ticker": ticker,
                            "snapshot": snapshot.isoformat(), "reason": reason,
                        })
                elif reason == "censored":
                    tally[horizon]["censored"] += 1
                else:
                    tally[horizon]["unlabeled"] += 1
    return {
        "quarters": [day.isoformat() for day in dates],
        "tickers_with_one_cik": companies_used,
        "ticker_cik_conflicts": len(conflicts),
        "tally": tally,
        "positive_examples": positives,
        "verified_negatives": 0,
    }


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def main():
    today = date.today()
    conn = connect(DB)
    base = counts(conn)
    snapshots, announcements, prices, coverage = load(conn)
    conn.close()
    audit = case_control_audit(snapshots, prices)
    spans = price_spans(prices)
    attempted = grid(snapshots, announcements, prices, today)
    controls = [row for row in snapshots if row["kind"] == "non_acquired"]
    phrase = sum((row.get("company_outcome") or "").startswith("no phrase hit") for row in controls)
    not_listed = sum("not in the current SEC ticker list" in (row.get("company_outcome") or "") for row in controls)
    generated = today.isoformat()
    dataset = {
        "constructed": False,
        "generatedOn": generated,
        "verifiedNegativeRows": 0,
        "rows": [],
        "reason": (
            "No market listing history is stored, and the absence of a verified deal "
            "is not a completed observation. Quarterly dates were counted and left unlabeled."
        ),
        "grid": {
            "quarters": len(attempted["quarters"]),
            "first": attempted["quarters"][0] if attempted["quarters"] else None,
            "last": attempted["quarters"][-1] if attempted["quarters"] else None,
            "tickers": attempted["tickers_with_one_cik"],
            "tally": attempted["tally"],
        },
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as handle:
        json.dump(dataset, handle, indent=2)
    context = {
        "today": generated, "base": base, "audit": audit, "spans": spans,
        "coverage": coverage, "controls": len(controls), "phrase": phrase,
        "not_listed": not_listed, "attempted": attempted,
        "target_rows": sum(row["kind"] == "target_pre" for row in snapshots),
        "target_deals": len({row["announcement_adsh"] for row in snapshots if row["kind"] == "target_pre"}),
    }
    write(os.path.join(REPORTS, "universe_sampling_bias.md"), sampling_report(context))
    write(os.path.join(REPORTS, "universe_label_quality.md"), label_report(context))
    write(os.path.join(REPORTS, "representative_universe.md"), universe_report(context))
    write(os.path.join(REPORTS, "universe_model_comparison.md"), comparison_report(context))
    write(os.path.join(REPORTS, "universe_calibration.md"), calibration_report(context))
    write(os.path.join(REPORTS, "universe_oos_evaluation.md"), evaluation_report(context))
    print("constructed", False)
    print("verified negatives", 0)
    for horizon in HORIZONS:
        print(horizon, attempted["tally"][horizon])
    print(OUT)


def sampling_report(ctx):
    coverage = ", ".join("%s %d" % (row["status"], row["n"]) for row in ctx["coverage"])
    audit = ctx["audit"]
    spans = ctx["spans"]
    return """# Sampling bias in the acquisition training sample

Generated %s. This describes the sample behind the existing XGBoost fit. It is not a new model.

## Companies shared by the training fold and the holdout

The chronological split keeps each CIK in one fold. Measured overlap of priced rows:

- Training and validation companies in both: %d
- Training and holdout companies in both: %d
- Validation and holdout companies in both: %d

Priced rows in those folds: training %d, validation %d, holdout %d. Companies: training %d, validation %d, holdout %d. Earlier deals of a later company are dropped rather than shared: %d priced rows were excluded that way.

Each company sits in one fold. The companies themselves still come from merger search hits and a small control draw.

## Several snapshots of one acquisition

Every verified deal has three target snapshots, at 30, 90, and 180 days before the announcement. That is %d deals and %d target rows. Among deals that have a stored price, %d still contribute more than one priced snapshot. In the holdout, %d deals contribute more than one priced snapshot. Those rows repeat one transaction.

## Positive labels are the offsets

A 30-day positive in this sample is the snapshot placed 30 days before a known announcement. The 90-day positive is the 30-day snapshot or the 90-day snapshot. There is no snapshot 31 to 60 days before the announcement, so the stored 60-day label matches the 30-day label.

## Negative labels are missing phrase matches

Non-acquired snapshots: %d. Of those, %d are stored with the outcome "no phrase hit for the merger queries in the next 180 days." The phrases are "merge with and into", "merged with and into", and "cash tender offer". %d of the controls are marked as absent from the current SEC ticker list. None of these rows is a verified statement that no acquisition was announced.

Target CIKs and control CIKs do not overlap (%s controls, drawn only from companies that were not already targets).

## Survivorship

Price requests and results: %s.

Symbols with no Yahoo listing: the historical company is often gone. Symbols whose current listing starts after the historical date were not given that new listing's bars. The 284 stored series are the names Yahoo still charts under the same symbol.

Those series are a window around the sampled event, from 420 days before it through up to 70 days after it. Stored span in calendar days: minimum %d, median %d, maximum %d. Series shorter than one year: %d of %d.

## Missing observation windows

- Unread item 1.01 search hits: %d
- Filings read: %d of %d search hits
- Search windows whose saved pages are short of the count EDGAR reported: %d
- SEC submission files on disk: %d. Company-facts files: %d. These are companies already in the deal extract, not a historical constituent list.
- News rows in historical_news_signals: %d
- No CRSP, Compustat, or exchange membership file is stored. WRDS was not logged in.

A representative listed universe, with a price and a complete announcement record on each date, is not on disk.
""" % (
        ctx["today"],
        audit["overlap"]["train_validation"], audit["overlap"]["train_test"], audit["overlap"]["validation_test"],
        audit["fold_rows"]["train"], audit["fold_rows"]["validation"], audit["fold_rows"]["test"],
        audit["fold_companies"]["train"], audit["fold_companies"]["validation"], audit["fold_companies"]["test"],
        audit["excluded_rows"],
        ctx["target_deals"], ctx["target_rows"],
        audit["deals_with_multiple_priced_snapshots"], audit["holdout_deals_with_multiple_snapshots"],
        ctx["controls"], ctx["phrase"], ctx["not_listed"], ctx["controls"],
        coverage,
        spans["min_days"], spans["median_days"], spans["max_days"], spans["under_one_year"], spans["tickers"],
        ctx["base"]["unread_101"], ctx["base"]["filings_read"], ctx["base"]["search_hits"],
        ctx["base"]["short_windows"], ctx["base"]["submission_files"], ctx["base"]["fact_files"],
        ctx["base"]["news_rows"],
    )


def label_report(ctx):
    tally = ctx["attempted"]["tally"]
    lines = [
        "# Label quality for a market-wide acquisition test",
        "",
        "Generated %s." % ctx["today"],
        "",
        "A positive would be a verified definitive target announcement inside the horizon. A negative would require the horizon to have ended and the announcement record for that company and window to be complete. A phrase search that returned nothing is not that record.",
        "",
        "The verified deal table has %d transactions and %d companies. %d companies have more than one verified deal. Unread item 1.01 hits: %d. Search windows short of EDGAR's reported count: %d. Because those holes exist, a company-date with no row in the deal table was left unlabeled." % (
            ctx["base"]["verified"], ctx["base"]["verified_ciks"], ctx["base"]["repeat_ciks"],
            ctx["base"]["unread_101"], ctx["base"]["short_windows"]),
        "",
        "The same rule applied to every quarter-end from 2016 through %s, for the %d stored tickers that map to one CIK:" % (
            ctx["today"], ctx["attempted"]["tickers_with_one_cik"]),
        "",
    ]
    for horizon in HORIZONS:
        item = tally[horizon]
        lines.append(
            "- %d-day: verified positives %d, censored %d, no price on or before the date %d, unlabeled %d, verified negatives 0."
            % (horizon, item["positive"], item["censored"], item["no_price"], item["unlabeled"])
        )
    lines.extend([
        "",
        "The 30-day, 60-day, and 90-day counts differ where a verified announcement falls inside the longer window. Those are distinct definitions. They were not turned into a training matrix, because the other company-dates are unlabeled rather than negative.",
        "",
        "Censored dates are quarter-ends whose horizon had not ended on %s. They were not coded as zero." % ctx["today"],
        "",
        "Ticker symbols that map to more than one CIK in the snapshots were left out of the grid: %d." % ctx["attempted"]["ticker_cik_conflicts"],
        "",
    ])
    return "\n".join(lines)


def universe_report(ctx):
    return """# Representative historical universe

Generated %s.

The universe was not constructed. `data/predictive/representative_universe.json` records that decision and contains no labeled company-dates.

## What a usable universe would need

- The companies listed on each prediction date, including names that later delisted or were acquired.
- A price on or before that date for each of those companies.
- Every definitive acquisition announcement, so a finished window with no announcement can be labeled zero.

## What is stored

- 749 verified target transactions, from the portion of the EDGAR phrase search that was read.
- 126 companies labeled non-acquired because three merger phrases returned no 8-K. That draw is 16 one-week slices of 10-K filers in 2021–2024, skipping companies already marked as targets.
- Yahoo bars for 284 symbols, each covering roughly the 420 days before a sampled event and up to 70 days after it. Median stored span: %d days.
- 174 symbols with no Yahoo listing and 52 whose current Yahoo listing starts after the historical date. Those bars were not invented.
- 792 SEC submission files and 252 company-facts files for companies already in this extract.
- No historical exchange membership, CRSP name history, or full-market ticker file.

Quarter-end dates from 2016 were checked against the stored bars. Company-dates with a price and a verified announcement inside the horizon were counted as positives. Every other finished company-date stayed unlabeled. Verified negatives written: 0.

Filling the unlabeled dates with zero, or copying the case-control sample forward, would manufacture the observations this check is supposed to test.
""" % (ctx["today"], ctx["spans"]["median_days"])


def comparison_report(ctx):
    return """# Market-wide model comparison

Generated %s.

Logistic regression, random forest, and XGBoost were not refit.

The existing XGBoost specification is depth 2, 160 trees, and lambda 1. Its saved experiment file does not contain the trees, and its training labels are the case-control offsets described in `reports/universe_sampling_bias.md`. Scoring that specification on the quarter-end grid would require treating unlabeled company-dates as negatives. That substitution is not made.

The historical acquisition base rate for a listed company over 30 days is not in the stored files. No published base rate was inserted.

Black-Scholes was not changed, and the experiment flag that would pass a probability into the acquisition valuation remains off.
""" % ctx["today"]


def calibration_report(ctx):
    return """# Probability calibration

Generated %s.

Platt scaling and isotonic regression were not fit.

Both methods need a calibration period of real outcomes that is separate from the final holdout. The files do not contain a market-wide set of verified positives and verified negatives, so there is no calibration period to hold out. The case-control fold was not used as a substitute, and the final holdout was not used either.

No calibrated probability was written.
""" % ctx["today"]


def evaluation_report(ctx):
    return """# Chronological out-of-sample evaluation

Generated %s.

A market-wide holdout was not scored. The eligible universe has zero verified negatives, so precision and recall among the highest-ranked names would not be a test of acquisition prediction.

| Measure | Result |
| --- | --- |
| PR-AUC | not computed |
| ROC-AUC | not computed |
| Brier score | not computed |
| Calibration curve | not computed |
| Precision@10 | not computed |
| Precision@20 | not computed |
| Recall@10 | not computed |
| Recall@20 | not computed |
| Lift over the market-wide 30-day base rate | not computed |

The market-wide base rate is missing for the same reason as the negatives: the listed population and the complete announcement record are not stored. The earlier case-control holdout, where about 30 percent of rows were pre-built 30-day offsets, is not this base rate and is not repeated here as predictive accuracy.

The results were not connected to Black-Scholes.
""" % ctx["today"]


if __name__ == "__main__":
    main()
