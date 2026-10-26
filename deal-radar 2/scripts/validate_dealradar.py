"""Diagnostic check of DealRadar's existing close-probability rules.

This does not change the production model. It calls terms.estimate_probabilities
and quote.close_probability, then writes reports/dealradar_quick_validation.md.

The rules estimate the chance an announced deal eventually closes. They do not
estimate the chance that a deal will be announced. A score is a valid historical
prediction only when its inputs were knowable before the announcement. Filing
flags are not knowable before the filing, so those rows fail the leakage check
and are left out of the Brier score.
"""
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import edgar
import quote
import server
import terms
import workflow

REPORT = os.path.join(ROOT, "reports", "dealradar_quick_validation.md")
LOOKBACK_DAYS = 120
EXTRA_POSITIVES = ("CCC", "ACVA", "PAG")
NEGATIVE_CANDIDATES = ("AAPL", "MSFT", "GOOGL", "JNJ", "KO", "WMT", "PG", "XOM", "JPM", "UNH")
SEARCHES = (
    ('"agreement and plan of merger"', "8-K"),
    ('"offer to purchase"', "SC TO-T"),
)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git_info():
    def run(args):
        return subprocess.check_output(args, cwd=ROOT, text=True).strip()

    head = run(["git", "rev-parse", "HEAD"])
    short = run(["git", "rev-parse", "--short", "HEAD"])
    subject = run(["git", "log", "-1", "--format=%s"])
    dirty = run(["git", "diff", "--name-only", "HEAD", "--", "terms.py", "quote.py", "news.py", "options.py"])
    return {"head": head, "short": short, "subject": subject, "probability_files_dirty": dirty}


def fetch_book():
    """Prefer the book the running app already built. Fall back to one scan."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/scan", timeout=90) as response:
            payload = json.load(response)
        if payload.get("mode") == "live" and payload.get("deals"):
            return payload["deals"], "The running app's GET /api/scan book", payload.get("scannedAt")
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    payload = server.scan(30, 12)
    return payload.get("deals") or [], "server.scan(30, 12)", payload.get("scannedAt")


def score_deal(deal):
    """Both production scores. The quote uses the log-odds score when the user has not typed one."""
    flags = dict(deal.get("flags") or {})
    consideration = deal.get("consideration")
    quoted = dict(flags)
    if consideration:
        quoted["consideration"] = consideration
    additive, pending, additive_drivers = terms.estimate_probabilities(consideration, flags)
    logit = quote.close_probability(quoted)
    return {
        "logit": logit["close"],
        "legacy_from_logit_path": logit["legacy"],
        "additive": additive,
        "pending": pending,
        "drivers": logit["drivers"],
        "additive_drivers": additive_drivers,
    }


def search_hits(cik):
    hits, errors = [], []
    for query, forms in SEARCHES:
        try:
            hits.extend(edgar.search_filings(
                server.EDGAR_UA, days=LOOKBACK_DAYS, query=query, forms=forms, ciks=cik))
        except (edgar.EdgarError, TimeoutError, OSError, ValueError) as exc:
            errors.append("%s: %s" % (forms, exc))
    return hits, errors


def select_positives(deals):
    chosen, seen = [], set()
    for deal in deals:
        ticker = (deal.get("ticker") or "").upper()
        if not ticker or ticker in seen or not workflow.active_quoted(deal):
            continue
        seen.add(ticker)
        chosen.append(deal)
        if len(chosen) >= 5:
            return chosen, []
    notes = []
    for ticker in EXTRA_POSITIVES:
        if ticker in seen or len(chosen) >= 5:
            break
        try:
            found = server.lookup_symbol(ticker)
        except (edgar.EdgarError, TimeoutError, OSError, ValueError) as exc:
            notes.append("%s lookup failed: %s" % (ticker, exc))
            continue
        deal = found.get("deal")
        if found.get("ok") and deal and workflow.active_quoted(deal):
            seen.add(ticker)
            chosen.append(deal)
            notes.append("%s was not in the current 12-filing scan. The existing company lookup read its filing." % ticker)
        else:
            notes.append("%s was not added: %s" % (ticker, found.get("message") or found.get("error") or "no quoted cash deal"))
    return chosen, notes


def select_negatives(run_day):
    rows, checked = [], []
    if not server.EDGAR_UA:
        return rows, ["EDGAR_USER_AGENT is not set, so non-deal companies could not be checked."]
    for ticker in NEGATIVE_CANDIDATES:
        if len(rows) >= 5:
            break
        try:
            company = edgar.find_company(server.EDGAR_UA, ticker)
        except (edgar.EdgarError, TimeoutError, OSError, ValueError) as exc:
            checked.append("%s: SEC company list failed: %s" % (ticker, exc))
            continue
        if not company:
            checked.append("%s: not on the SEC company list." % ticker)
            continue
        hits, errors = search_hits(company["cik"])
        checked.append("%s (%s): %d merger or tender hit(s) in %d days.%s" % (
            company["ticker"], company["name"], len(hits), LOOKBACK_DAYS,
            (" Errors: " + " ".join(errors)) if errors else ""))
        if errors and not hits:
            continue
        if hits:
            continue
        rows.append({
            "ticker": company["ticker"],
            "name": company["name"],
            "cik": company["cik"],
            "outcome": 0,
            "announcement": None,
            "source": (
                "SEC EDGAR full-text search for CIK %s. No 8-K containing "
                "\"agreement and plan of merger\" and no SC TO-T containing "
                "\"offer to purchase\" in the %d days ending %s."
            ) % (company["cik"], LOOKBACK_DAYS, run_day),
            "probability": None,
            "scored": False,
            "reason": "The production path does not emit a close probability when no merger filing was read.",
        })
    return rows, checked


def brier(probability, outcome):
    return (probability - outcome) ** 2


def roc_auc(pairs):
    """pairs: (score, outcome). None when either class is missing."""
    pos = [score for score, outcome in pairs if outcome == 1]
    neg = [score for score, outcome in pairs if outcome == 0]
    if not pos or not neg:
        return None
    ordered = sorted(pairs, key=lambda item: item[0])
    rank = {}
    index = 0
    while index < len(ordered):
        stop = index
        while stop + 1 < len(ordered) and ordered[stop + 1][0] == ordered[index][0]:
            stop += 1
        average = (index + stop) / 2.0 + 1.0
        for cursor in range(index, stop + 1):
            rank[id(ordered[cursor])] = average
        index = stop + 1
    rank_sum = sum(rank[id(item)] for item in ordered if item[1] == 1)
    return (rank_sum - len(pos) * (len(pos) + 1) / 2.0) / (len(pos) * len(neg))


def cell(value):
    return str(value).replace("|", "/").replace("\n", " ")


def build_report(meta, positives, negatives, notes, negative_log, blank):
    valid = [row for row in positives + negatives if row.get("valid")]
    scored = [row for row in positives if row.get("scored")]
    lines = []
    add = lines.append
    add("# DealRadar quick validation")
    add("")
    add("Run at %s. Git %s, %s." % (meta["run_at"], meta["git"]["short"], meta["git"]["subject"].rstrip(".")))
    add("")
    add("**Verdict: TEST BLOCKED — MODEL OR DATA ACCESS ISSUE**")
    add("")
    add("This run executed the existing close-probability rules. It did not produce a valid historical prediction, so no Brier score is reported as evidence of accuracy.")
    add("")
    add("## 1. The probability calculation")
    add("")
    add("DealRadar does not calculate the probability that a merger will be announced. `pClose` is the chance that an already announced deal eventually closes.")
    add("")
    add("Two production functions implement that chance. Neither was modified for this test.")
    add("")
    add("- `quote.close_probability` is the score used by the stock quote and by the on-screen chance before any headline adjustment. It starts at log-odds of **0.90** (`quote.BASE_P`). Each filing flag adds its point adjustment divided by `SCALE = 0.09`, then the result is passed through a logistic function.")
    add("- `terms.estimate_probabilities` is the number stored on the deal as `pClose`. It starts at **0.93**, adds the same point adjustments directly, and clamps the result to 0.35–0.98.")
    add("")
    add("The point adjustments, applied only when the filing text sets the flag, are:")
    add("")
    add("| Signal | Points |")
    add("|---|---:|")
    add("| US antitrust filing (HSR) | -0.01 |")
    add("| Second request | -0.10 |")
    add("| Each foreign approval, capped at three | -0.03 |")
    add("| Each sector approval, capped at two | -0.03 |")
    add("| Financing condition | -0.06 |")
    add("| Financing explicitly not required | +0.01 |")
    add("| Tender offer | +0.02 |")
    add("| Shareholder vote, and no tender | -0.01 |")
    add("| Go-shop | -0.01 |")
    add("| Payment in the buyer's stock | -0.02 |")
    add("")
    add("A call with no flags returns %.4f from `quote.close_probability` and %.3f from `terms.estimate_probabilities`. Those are the announced-deal base rates, not a probability that no deal exists." % (
        blank["logit"], blank["additive"]))
    add("")
    add("`data/model.json` is absent, so no trained model is loaded. The hand-written 0.90 and 0.93 figures are judgments. They are not an announcement frequency measured on a training set. Live Yahoo headlines are not applied here, because a headline fetched today can mention an announcement that has already happened.")
    add("")
    add("Probability source files differ from git HEAD: %s." % (meta["git"]["probability_files_dirty"] or "no"))
    add("")
    add("## 2. The ten companies")
    add("")
    add("Announced deals are companies already in DealRadar for which `workflow.active_quoted` is true: a filing sentence quoted a per-share price, and the filing was not classified as a termination or a completed close. The book source was %s, scanned at %s." % (
        meta["book_source"], meta["scanned_at"] or "unknown"))
    add("")
    add("Companies without an announced deal were checked with the same EDGAR searches the app uses for one company, over the %d days ending on the run date. A company is in this group only when both searches returned zero hits. That is evidence about this window, not a claim that the company will never be acquired." % LOOKBACK_DAYS)
    add("")
    add("| Company | Ticker | Role | Announcement filing | Outcome | Source |")
    add("|---|---|---|---|---:|---|")
    for row in positives + negatives:
        add("| %s | %s | %s | %s | %d | %s |" % (
            cell(row["name"]), cell(row["ticker"]), row["role"],
            cell(row["announcement"] or "None in the search window"),
            row["outcome"], cell(row["source"])))
    add("")
    if notes:
        add("Positive-company notes:")
        add("")
        for note in notes:
            add("- %s" % note)
        add("")
    add("Negative-company checks:")
    add("")
    for note in negative_log:
        add("- %s" % note)
    add("")
    add("## 3. What the existing functions returned")
    add("")
    add("The prediction timestamp for every row is the run time, %s. That is when the functions were called. It is not a date before the announcements." % meta["run_at"])
    add("")
    add("| Company | Quote probability | Stored additive probability | Filing date | Outcome | Leakage check |")
    add("|---|---:|---:|---|---:|---|")
    for row in positives:
        add("| %s | %.4f | %.3f | %s | %d | Failed. The inputs are flags from the announcement filing. |" % (
            cell(row["ticker"]), row["logit"], row["additive"], cell(row["announcement"]), row["outcome"]))
    for row in negatives:
        add("| %s | Not scored | Not scored | None in the search window | 0 | No probability was emitted. |" % cell(row["ticker"]))
    add("")
    add("Signal contributions for the announced deals, from `quote.close_probability`:")
    add("")
    for row in positives:
        parts = []
        for driver in row["drivers"]:
            if abs(driver.get("logOdds") or 0) < 1e-9 and "9 in 10" not in driver.get("label", ""):
                continue
            parts.append("%s (%s)" % (driver["label"], driver.get("logOdds")))
        add("- **%s:** %s" % (row["ticker"], "; ".join(parts) if parts else "base rate only"))
    add("")
    add("The cash or stock price, the stock price, and the break price are not inputs to either probability function. They are used only later, for the bid and ask.")
    add("")
    add("## 4. Historical-data limits")
    add("")
    add("- No snapshot of these flags was saved before each announcement. The flags were read from the announcement filing on this run.")
    add("- No pre-announcement price series was passed into the probability. The function would not use it if one were passed.")
    add("- No trained model file and no saved training-set announcement rate are in the repository.")
    add("- Companies outside the current scan were read through the existing lookup, which still reads the current filing, not an archived pre-announcement record.")
    add("- A zero search result covers %d days, not the company's whole history." % LOOKBACK_DAYS)
    add("")
    add("## 5. Individual Brier scores")
    add("")
    add("Brier score = (predicted probability - outcome)^2. A row is included only when the probability was produced from information available before the outcome.")
    add("")
    add("| Company | Predicted probability | Outcome | Brier score |")
    add("|---|---:|---:|---:|")
    for row in positives + negatives:
        add("| %s | Not a valid pre-outcome prediction | %d | Not calculated |" % (cell(row["ticker"]), row["outcome"]))
    add("")
    add("Scored announced deals: %d. Valid Brier rows: %d. Unscored non-deal companies: %d. None of the scored rows passed the leakage check, so none entered the average." % (
        len(scored), len(valid), len(negatives)))
    add("")
    add("## 6. Mean Brier score and baseline")
    add("")
    add("Mean Brier score: **not calculated**. The denominator of valid predictions is 0.")
    add("")
    add("Baseline: **not calculated**. The instruction is to use the announcement frequency in the training data, and not the frequency in these 10 cases. There is no training set loaded. The 0.90 and 0.93 constants are close rates for announced deals, so using either one as an announcement baseline would answer a different question.")
    add("")
    add("## 7. ROC AUC")
    add("")
    add("ROC AUC: **not calculated**. It needs a leakage-free score for at least one announced deal and one company without an announced deal. This run has no leakage-free scores.")
    add("")
    add("The announced deals that were scored sit at %.4f to %.4f on the quote scale. A call with no flags returns %.4f. The production path therefore does not give a company a lower probability merely because no announcement was found. It gives that company no probability at all." % (
        min(row["logit"] for row in scored) if scored else float("nan"),
        max(row["logit"] for row in scored) if scored else float("nan"),
        blank["logit"]))
    add("")
    add("## 8. Leakage and other failures")
    add("")
    add("- Every scored probability uses the merger or tender filing. That filing is the announcement, so the input contains the outcome this test would be trying to predict.")
    add("- The same transaction is not in a training set, because no training set is loaded. There is also no held-out historical sample.")
    add("- Missing pre-announcement inputs are listed above. They were not filled in.")
    add("- Non-deal companies stayed in the report with probability \"Not scored\". They were not dropped and were not assigned 0.90 or 0.93.")
    add("- This is a retrospective diagnostic of the current rules. It is not a historical predictive backtest.")
    add("")
    if len(positives) < 5 or len(negatives) < 5:
        add("The run also fell short of the requested 5 and 5 companies: %d announced deals and %d companies with no matching filing. Shortfall details are in the company notes. No extra companies were invented to fill the table." % (
            len(positives), len(negatives)))
        add("")
    add("## 9. Verdict")
    add("")
    add("**TEST BLOCKED — MODEL OR DATA ACCESS ISSUE**")
    add("")
    add("The existing function ran. A valid test of whether it ranks future announcements did not. The smallest next step is to save, for each company and for a date before its announcement, the inputs the function can actually see. Today those inputs are only filing flags, and the flags do not exist until the announcement filing exists. Until the model has a pre-announcement input, a Brier score against later announcements is not measurable.")
    add("")
    return "\n".join(lines) + "\n"


def main():
    run_at = utc_now()
    run_day = run_at[:10]
    info = git_info()
    deals, book_source, scanned_at = fetch_book()
    positives_raw, notes = select_positives(deals)
    positives = []
    for deal in positives_raw:
        scored = score_deal(deal)
        url = deal.get("docUrl") or deal.get("indexUrl") or "SEC filing in the current book"
        positives.append({
            "ticker": (deal.get("ticker") or "").upper(),
            "name": deal.get("target") or deal.get("ticker"),
            "role": "Announced deal",
            "announcement": deal.get("filedOn"),
            "outcome": 1,
            "source": "%s %s filed %s. %s" % (
                deal.get("form") or "Filing", url, deal.get("filedOn") or "unknown date",
                "Per-share price quoted from the filing." if deal.get("offer") else "No per-share price."),
            "logit": scored["logit"],
            "additive": scored["additive"],
            "drivers": scored["drivers"],
            "scored": True,
            "valid": False,
        })
    negatives, negative_log = select_negatives(run_day)
    for row in negatives:
        row["role"] = "No announcement in the search window"
        row["valid"] = False
    blank_logit = quote.close_probability({})
    blank_additive, _, _ = terms.estimate_probabilities(None, {})
    blank = {"logit": blank_logit["close"], "additive": blank_additive}
    meta = {
        "run_at": run_at,
        "git": info,
        "book_source": book_source,
        "scanned_at": scanned_at,
    }
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    report = build_report(meta, positives, negatives, notes, negative_log, blank)
    with open(REPORT, "w", encoding="utf-8") as handle:
        handle.write(report)
    valid = 0
    print("run_at %s" % run_at)
    print("announced %d" % len(positives))
    print("no_announcement %d" % len(negatives))
    print("valid_brier_cases %d" % valid)
    print("mean_brier not_calculated")
    print("baseline not_calculated")
    print("roc_auc not_calculated")
    print("verdict TEST BLOCKED — MODEL OR DATA ACCESS ISSUE")
    for row in positives:
        print("positive %s quote=%.4f additive=%.3f filed=%s" % (
            row["ticker"], row["logit"], row["additive"], row["announcement"]))
    for row in negatives:
        print("negative %s %s not_scored" % (row["ticker"], row["name"]))
    print("blank_quote %.4f blank_additive %.3f" % (blank["logit"], blank["additive"]))
    print("report %s" % REPORT)
    if len(positives) < 1 or len(negatives) < 1:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
