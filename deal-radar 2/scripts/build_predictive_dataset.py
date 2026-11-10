"""Build the historical research dataset and refuse to train if it is too small.

    python3 scripts/build_predictive_dataset.py

Reads cached filings and cached pre-announcement prices. Asks Yahoo for
post-announcement prices of deals that are still listed, and for the older
delisted tickers. Does not write data/model.json and does not change
quote.close_probability.
"""
import csv
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import market
import quote
import terms
from experimental.preannouncement import bars_before, price_features
from predictive.gates import ACQUISITION, CLOSING, PRICE, acquisition_ready, closing_ready, price_ready
from predictive.sources import SourceError, financial_modeling_prep, historical_news, polygon
import ablate_signals

OUT = os.path.join(ROOT, "data", "predictive")
REPORTS = os.path.join(ROOT, "reports")
PRICE_CACHE = os.path.join(ROOT, "data", "preannouncement_prototype", "prices")
FILING_CACHE = os.path.join(ROOT, "data", "preannouncement_prototype", "filings")
ANNOUNCEMENTS = os.path.join(ROOT, "data", "closing_validation", "announcements")

# Filings read in the September 2026 prototype. Dates are the SEC file dates.
PRE_TARGETS = [
    {"name": "GoPro, Inc.", "ticker": "GPRO", "cik": 1500435, "adsh": "0001628280-26-060181",
     "filed": "2026-09-02", "prediction": "2026-08-03", "window": ("2026-02-04", "2026-08-03")},
    {"name": "ACV Auctions Inc.", "ticker": "ACVA", "cik": 1637873, "adsh": "0000950103-26-013780",
     "filed": "2026-09-10", "prediction": "2026-08-11", "window": ("2026-02-12", "2026-08-11")},
    {"name": "Mistras Group, Inc.", "ticker": "MG", "cik": 1436126, "adsh": "0001140361-26-037107",
     "filed": "2026-09-18", "prediction": "2026-08-19", "window": ("2026-02-20", "2026-08-19")},
    {"name": "Centerspace", "ticker": "CSR", "cik": 798359, "adsh": "0001140361-26-035986",
     "filed": "2026-09-09", "prediction": "2026-08-10", "window": ("2026-02-11", "2026-08-10")},
]
PRE_CONTROLS = [
    {"name": "Apple Inc.", "ticker": "AAPL", "cik": 320193, "prediction": "2026-08-03", "window": ("2026-02-04", "2026-08-03")},
    {"name": "Microsoft Corp.", "ticker": "MSFT", "cik": 789019, "prediction": "2026-08-11", "window": ("2026-02-12", "2026-08-11")},
    {"name": "Alphabet Inc.", "ticker": "GOOGL", "cik": 1652044, "prediction": "2026-08-19", "window": ("2026-02-20", "2026-08-19")},
    {"name": "Johnson & Johnson", "ticker": "JNJ", "cik": 200406, "prediction": "2026-08-10", "window": ("2026-02-11", "2026-08-10")},
]


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def parse_day(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def load_cached_series(ticker, start, end):
    path = os.path.join(PRICE_CACHE, "%s_%s_%s.json" % (ticker, start, end))
    if not os.path.exists(path):
        return None, path
    rows = json.loads(open(path, encoding="utf-8").read())
    return [(parse_day(day), float(close)) for day, close in rows], path


def trading_offset(series, anchor, sessions):
    """The close `sessions` trading days after the first bar on or after anchor."""
    after = [(day, close) for day, close in series if day >= anchor]
    if len(after) <= sessions:
        return None
    day, close = after[sessions]
    return {"date": day.isoformat(), "close": close}


def source_notes():
    notes = []
    for probe in (financial_modeling_prep, polygon, historical_news):
        try:
            probe()
        except SourceError as exc:
            notes.append(str(exc))
    notes.append("Yahoo daily chart via market.history. Delayed bars. Delisted symbols often return HTTP 400 or 404.")
    notes.append("SEC EDGAR full-text search can take a historical start and end. Production search_filings still ends on today.")
    notes.append("Options chains are unavailable. Yahoo's options endpoint returned HTTP 401 and is not bypassed.")
    notes.append("yfinance is not used. It is not installed, and it is not a way around the options refusal.")
    return notes


def pre_rows():
    rows = []
    for case, label in [(item, 1) for item in PRE_TARGETS] + [(item, 0) for item in PRE_CONTROLS]:
        start, end = case["window"]
        stock, stock_path = load_cached_series(case["ticker"], start, end)
        spy, spy_path = load_cached_series("SPY", start, end)
        prediction = parse_day(case["prediction"])
        missing = []
        features = None
        error = None
        if stock is None:
            missing.append("cached pre-announcement prices")
            error = "No cached Yahoo series at %s." % stock_path
        elif spy is None:
            missing.append("cached SPY prices")
            error = "No cached SPY series at %s." % spy_path
        else:
            try:
                features = price_features(bars_before(stock, prediction), bars_before(spy, prediction))
            except ValueError as exc:
                error = str(exc)
                missing.append("21 trading sessions before the prediction date")
        rows.append({
            "task": "acquisition_30d",
            "name": case["name"],
            "ticker": case["ticker"],
            "cik": case.get("cik"),
            "predictionDate": case["prediction"],
            "announcementDate": case.get("filed"),
            "label": label,
            "labelMeaning": "Qualifying acquisition announcement within 30 days." if label else "No qualifying announcement in the searched window.",
            "features": features,
            "scoreName": "abnormal_21_ranking",
            "score": None if not features else features["abnormal_21"],
            "probability": None,
            "missing": missing,
            "error": error,
            "sources": ["yahoo-chart cache", "sec filing" if label else "sec full-text search"],
            "retrievedFrom": stock_path if stock is not None else None,
        })
    return rows


def close_rows():
    rows = []
    for name, ticker, announced, label, compact, _published in ablate_signals.DEALS:
        adsh = ablate_signals.adsh(compact)
        path = os.path.join(ANNOUNCEMENTS, adsh + ".txt")
        text = open(path, encoding="utf-8", errors="replace").read() if os.path.exists(path) else ""
        extracted = terms.extract_terms(text) if text else {"offer": None, "consideration": None, "flags": {}}
        scored = quote.close_probability(extracted.get("flags") or {})
        rows.append({
            "task": "deal_close",
            "name": name,
            "ticker": ticker,
            "announcementDate": announced,
            "label": label,
            "labelMeaning": "Closed" if label else "Terminated",
            "offer": extracted.get("offer"),
            "consideration": extracted.get("consideration"),
            "heuristicClose": scored["close"],
            "probability": None,
            "featuresFrom": "announcement filing flags. Not usable before the announcement.",
            "source": path,
        })
    return rows


def yahoo_prices(ticker, start, end):
    try:
        series = market.history(ticker, start, end)
        return series, None
    except market.MarketError as exc:
        return None, str(exc)


def post_rows():
    """Observed prices after the four announcements. These are outcomes, not features."""
    rows = []
    for case in PRE_TARGETS:
        filed = parse_day(case["filed"])
        series, error = yahoo_prices(case["ticker"], filed - timedelta(days=10), date(2026, 11, 8))
        filing = os.path.join(FILING_CACHE, case["adsh"] + ".txt")
        offer = None
        evidence = ""
        if os.path.exists(filing):
            extracted = terms.extract_terms(open(filing, encoding="utf-8", errors="replace").read())
            evidence = ((extracted.get("evidence") or {}).get("offer") or "")
            low = evidence.lower()
            # Keep a cash per-share price. A dividend cap is not the acquisition price.
            if "dividend" not in low and "per share" in low and ("cash" in low or "offer price" in low):
                offer = extracted.get("offer")
        observed = {}
        pre = None
        if series:
            before = [(day, close) for day, close in series if day < filed]
            pre = None if not before else {"date": before[-1][0].isoformat(), "close": before[-1][1]}
            for name, sessions in (("immediate", 0), ("day1", 1), ("day5", 5), ("day10", 10), ("day30", 30)):
                observed[name] = trading_offset(series, filed, sessions)
        rows.append({
            "task": "post_announcement_price",
            "name": case["name"],
            "ticker": case["ticker"],
            "announcementDate": case["filed"],
            "offer": offer,
            "preClose": pre,
            "observed": observed,
            "predictedPrice": None,
            "error": error,
            "source": "yahoo-chart retrieved %s" % iso_now(),
        })
    return rows


# Trading symbols read from the June 2023 8-K covers. The closing-test list often
# stores a company name or the buyer's ticker in the ticker field.
JUNE_TARGETS = [
    ("CIR", "2023-06-05"),
    ("PRTK", "2023-06-07"),
    ("KDNY", "2023-06-12"),
    ("NEX", "2023-06-15"),
    ("DICE", "2023-06-20"),
    ("QUOT", "2023-06-20"),
    ("CFMS", "2023-06-23"),
    ("SGTX", "2023-06-29"),
    ("KLR", "2023-06-30"),
]


def delisted_checks():
    """Ask Yahoo again for the June 2023 target symbols. Record the answer. Do not fill a price."""
    symbols = []
    for ticker, announced in JUNE_TARGETS:
        filed = parse_day(announced)
        series, error = yahoo_prices(ticker, filed - timedelta(days=40), filed)
        symbols.append({
            "ticker": ticker, "announcementDate": announced, "error": error,
            "bars": 0 if series is None else len(series),
        })
    return symbols


def write_csv(path, pre, closes, posts):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["task", "ticker", "date", "label", "value_name", "value", "note"])
        for row in pre:
            writer.writerow([
                row["task"], row["ticker"], row["predictionDate"], row["label"],
                row["scoreName"], "" if row["score"] is None else "%.6f" % row["score"],
                "Ranking score from prices before the prediction date. Not a probability.",
            ])
        for row in closes:
            writer.writerow([
                row["task"], row["ticker"], row["announcementDate"], row["label"],
                "quote.close_probability", "%.6f" % row["heuristicClose"],
                "Existing announced-deal heuristic. Not a newly trained model.",
            ])
        for row in posts:
            pre_close = (row.get("preClose") or {}).get("close")
            immediate = (row.get("observed") or {}).get("immediate") or {}
            writer.writerow([
                row["task"], row["ticker"], row["announcementDate"], "",
                "observed_immediate_close", "" if immediate.get("close") is None else "%.4f" % immediate["close"],
                "Observed Yahoo close. Predicted price is blank. Pre-close %s." % ("" if pre_close is None else "%.4f" % pre_close),
            ])


def write_reports(manifest, pre, closes, posts, delisted, notes):
    os.makedirs(REPORTS, exist_ok=True)
    perf = {
        "generatedAt": manifest["generatedAt"],
        "trained": False,
        "models": manifest["models"],
        "note": "No model was fit. Metrics that need a held-out prediction are null.",
    }
    with open(os.path.join(REPORTS, "model_performance_report.json"), "w", encoding="utf-8") as handle:
        json.dump(perf, handle, indent=2)
    with open(os.path.join(REPORTS, "feature_importance.json"), "w", encoding="utf-8") as handle:
        json.dump({"fitted": False, "features": [], "reason": manifest["reason"]}, handle, indent=2)

    lines = []
    add = lines.append
    add("# Model performance")
    add("")
    add("Generated %s. No acquisition, price, or closing model was trained." % manifest["generatedAt"])
    add("")
    add(manifest["reason"])
    add("")
    add("## Acquisition within 30, 90, and 180 days")
    add("")
    add("Usable 30-day rows with a pre-announcement price feature: %d (%d later announced, %d did not)." % (
        manifest["counts"]["acquisitionRows"], manifest["counts"]["acquisitionPositives"], manifest["counts"]["acquisitionNegatives"]))
    add("")
    add("A model needs %d rows, %d announcements, %d non-announcements, and %d held-out rows. This run has none of the 90-day or 180-day labels, because those windows were not built. Precision, recall, PR-AUC, ROC-AUC, Brier score, and calibration were not calculated." % (
        ACQUISITION["rows"], ACQUISITION["positives"], ACQUISITION["negatives"], ACQUISITION["holdout"]))
    add("")
    add("The abnormal 21-session return is stored in `backtest_results.csv` as a ranking score. It is not a probability.")
    add("")
    add("## Post-announcement price")
    add("")
    add("Deals with both a pre-announcement close and at least one observed post-announcement close: %d. A price model needs %d. Mean absolute error was not calculated, because there is no predicted price." % (
        manifest["counts"]["priceDeals"], PRICE["deals"]))
    add("")
    for row in posts:
        immediate = (row.get("observed") or {}).get("immediate")
        if row["error"]:
            add("- %s: %s" % (row["ticker"], row["error"]))
        elif immediate:
            add("- %s: last close before the filing %s, first close on or after the filing %s on %s. Offer from the filing: %s. No predicted price." % (
                row["ticker"],
                "missing" if not row["preClose"] else "%.2f" % row["preClose"]["close"],
                "%.2f" % immediate["close"], immediate["date"],
                "not found" if row["offer"] is None else "%.2f" % row["offer"]))
        else:
            add("- %s: Yahoo returned bars, but none fall on or after the filing date." % row["ticker"])
    add("")
    add("## Deal completion")
    add("")
    add("Labeled announced deals on disk: %d, of which %d terminated. A closing model needs %d deals and %d terminations. The existing `quote.close_probability` values are listed in the CSV. They remain the hand-set 0.90 rule. They were not refit." % (
        len(closes), sum(1 for row in closes if row["label"] == 0), CLOSING["deals"], CLOSING["terminations"]))
    add("")
    path = os.path.join(REPORTS, "model_performance_report.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip() + "\n")

    data_lines = []
    put = data_lines.append
    put("# Historical dataset")
    put("")
    put("Generated %s." % manifest["generatedAt"])
    put("")
    put("## What was collected")
    put("")
    put("- 30-day pre-announcement rows with a cached price feature: %d." % manifest["counts"]["acquisitionRows"])
    put("- Announced deals with a close or termination label from the earlier closing test: %d (%d terminated)." % (
        len(closes), sum(1 for row in closes if row["label"] == 0)))
    put("- Still-listed targets with a post-announcement Yahoo close: %d." % manifest["counts"]["priceDeals"])
    put("- June 2023 symbols asked of Yahoo again: %d. Prices returned: %d." % (
        len(delisted), sum(1 for row in delisted if not row["error"])))
    put("")
    put("Rows are in `data/predictive/observations.jsonl`. Each price row names its cache file or the Yahoo error. No missing price was filled in.")
    put("")
    put("## What is missing")
    put("")
    for note in notes:
        put("- " + note)
    put("- Revenue, EBITDA, market cap, enterprise value, debt, cash, price-to-earnings, price-to-sales, and institutional ownership. No point-in-time fundamentals source is connected.")
    put("- Acquirer identity is in some filing texts and was not turned into a learned acquirer model.")
    put("- Deal value, regulatory flags, and consideration are parsed only for the 18 cached closing-test filings, and only as announcement-time fields.")
    put("- 90-day and 180-day acquisition labels.")
    put("- A survivorship-safe set of delisted companies. Yahoo did not return their charts.")
    put("")
    put("## June 2023 price check")
    put("")
    if not delisted:
        put("No symbol from that set was sent to Yahoo.")
    for row in delisted:
        put("- %s, announcement %s: %s" % (row["ticker"], row["announcementDate"], row["error"] or "prices returned"))
    put("")
    put("## Look-ahead rule")
    put("")
    put("The 30-day features use only chart dates before the prediction date. The announcement filing is the label, not a feature. Closing-model flags come from the announcement, so they are excluded from the pre-announcement rows. Post-announcement prices are outcomes for a price study, and they are not copied into the pre-announcement features.")
    put("")
    with open(os.path.join(REPORTS, "historical_dataset_report.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(data_lines).rstrip() + "\n")

    audit = []
    say = audit.append
    say("# DealRadar predictive audit")
    say("")
    say("Generated %s. The live close-probability rules were not changed." % manifest["generatedAt"])
    say("")
    say("## What the app does now")
    say("")
    say("DealRadar scans SEC filings for a merger agreement or a tender offer, reads a cash price from the filing, and prices an option around that announced deal. The chance shown on a deal is the chance the announced deal eventually closes.")
    say("")
    say("`quote.close_probability` starts at %.2f and moves filing flags in log-odds. With no flags it returns %.4f. `terms.estimate_probabilities` starts at 0.93, adds the same flags, and clamps the result. `server.build_deal` stores that 0.93-based number unless `data/model.json` exists. That file is absent, so `model.load()` returns nothing." % (
        quote.BASE_P, quote.close_probability({})["close"]))
    say("")
    say("`training/train.py` can fit a logistic regression and a gradient booster on announcement-filing features, split by date. It has not been run on a collected label file in this project. Its `--demo` path uses synthetic deals and writes `data/model.demo.json`, which the server refuses to load.")
    say("")
    say("The earlier tests on 18 announced deals found that the filing flags do not beat a flat 0.90 close rate by more than noise. The pre-announcement experiment produced a 21-day abnormal-return ranking score for 4 targets and 4 large companies. That score is not a calibrated probability, and its average did not rank the targets above the other companies.")
    say("")
    say("## What is missing")
    say("")
    say("- A point-in-time dataset large enough for a 30-day, 90-day, and 180-day acquisition probability.")
    say("- Fundamentals, ownership, historical news, and options history.")
    say("- Prices for acquired companies after they leave Yahoo's chart.")
    say("- A trained, calibrated closing model with enough terminated deals.")
    say("- A model of the traded price after an announcement, as distinct from the offer price.")
    say("")
    say("## What this pass changed")
    say("")
    say("Research code lives in `predictive/` and `scripts/build_predictive_dataset.py`. It writes the dataset report, the performance report, `feature_importance.json`, and `backtest_results.csv`. It saves a model only when the sample gates in `predictive/gates.py` pass. They did not pass, so no probabilities were produced and the company list is unchanged.")
    say("")
    say("The status line on the page says the acquisition model is not trained. The 90% figure on an announced deal is still the closing rule, not the chance a company will be acquired.")
    say("")
    say("## Later phases, in order")
    say("")
    say("1. Keep collecting target and non-target companies with a fixed horizon, and store a price source that still has delisted symbols.")
    say("2. Add 90-day and 180-day labels from the same point-in-time rule. Do not multiply the 30-day score.")
    say("3. Fit logistic regression first. Compare it with a base rate on a later period. Add a tree model only when that comparison is possible.")
    say("4. Build the post-announcement price set until there are at least %d deals with a pre-close and a post-close." % PRICE["deals"])
    say("5. Fit a closing model only after at least %d announced deals and %d terminations." % (CLOSING["deals"], CLOSING["terminations"]))
    say("6. Show probabilities on the company list only after a saved model clears those gates.")
    say("")
    with open(os.path.join(REPORTS, "dealradar_predictive_audit.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(audit).rstrip() + "\n")


def main():
    os.makedirs(OUT, exist_ok=True)
    notes = source_notes()
    pre = pre_rows()
    closes = close_rows()
    posts = post_rows()
    delisted = delisted_checks()
    usable_pre = [row for row in pre if row["features"]]
    price_deals = [row for row in posts if row.get("preClose") and (row.get("observed") or {}).get("immediate")]
    terminations = sum(1 for row in closes if row["label"] == 0)
    counts = {
        "acquisitionRows": len(usable_pre),
        "acquisitionPositives": sum(1 for row in usable_pre if row["label"] == 1),
        "acquisitionNegatives": sum(1 for row in usable_pre if row["label"] == 0),
        "holdout": 0,
        "priceDeals": len(price_deals),
        "closingDeals": len(closes),
        "terminations": terminations,
    }
    ready_a, miss_a = acquisition_ready({
        "rows": counts["acquisitionRows"],
        "positives": counts["acquisitionPositives"],
        "negatives": counts["acquisitionNegatives"],
        "holdout": counts["holdout"],
    })
    ready_b, miss_b = price_ready({"deals": counts["priceDeals"]})
    ready_c, miss_c = closing_ready({"deals": counts["closingDeals"], "terminations": counts["terminations"]})
    reason = "Not enough point-in-time rows to train. No acquisition probability was produced."
    manifest = {
        "generatedAt": iso_now(),
        "trained": False,
        "reason": reason,
        "counts": counts,
        "models": {
            "acquisition": {"trained": ready_a, "missing": miss_a, "horizons": {"30": counts["acquisitionRows"], "90": 0, "180": 0}},
            "postAnnouncementPrice": {"trained": ready_b, "missing": miss_b},
            "dealClose": {"trained": ready_c, "missing": miss_c},
        },
    }
    observations = pre + closes + posts
    with open(os.path.join(OUT, "observations.jsonl"), "w", encoding="utf-8") as handle:
        for row in observations:
            handle.write(json.dumps(row) + "\n")
    with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    write_csv(os.path.join(REPORTS, "backtest_results.csv"), pre, closes, posts)
    write_reports(manifest, pre, closes, posts, delisted, notes)
    print("trained %s" % manifest["trained"])
    print("acquisition %d price_deals %d closes %d terminations %d" % (
        counts["acquisitionRows"], counts["priceDeals"], counts["closingDeals"], counts["terminations"]))
    print("gates acquisition %s price %s close %s" % (miss_a, miss_b, miss_c))
    for row in posts:
        immediate = (row.get("observed") or {}).get("immediate")
        print("post", row["ticker"], "err" if row["error"] else immediate)
    for row in delisted:
        print("old", row["ticker"], (row["error"] or "ok")[:80])
    return 0


if __name__ == "__main__":
    sys.exit(main())
